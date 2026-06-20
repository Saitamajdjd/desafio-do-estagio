import logging
import os
import re
import sys
from typing import Any

import requests
from dotenv import load_dotenv


MAXIMO_CONTATOS = 3
TABELA_CONTATOS = "contatos"
MODELO_MENSAGEM = "Olá, {nome} tudo bem com você?"


def configurar_logs() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def obter_variavel_obrigatoria(nome: str) -> str:
    valor = os.getenv(nome)
    if not valor:
        raise RuntimeError(f"Variável de ambiente obrigatória não encontrada: {nome}")
    return valor


def modo_teste_ativo() -> bool:
    return os.getenv("DRY_RUN", "false").strip().lower() in {"1", "true", "yes", "sim"}


def conectar_supabase() -> Any:
    try:
        from supabase import create_client
    except ImportError as exc:
        raise RuntimeError(
            "Pacote 'supabase' não instalado. Rode: pip install -r requirements.txt"
        ) from exc

    url_supabase = obter_variavel_obrigatoria("SUPABASE_URL")
    chave_supabase = obter_variavel_obrigatoria("SUPABASE_KEY")
    return create_client(url_supabase, chave_supabase)


def buscar_contatos(supabase: Any) -> list[dict[str, Any]]:
    logging.info("Buscando até %s contatos no Supabase...", MAXIMO_CONTATOS)

    try:
        resposta = (
            supabase.table(TABELA_CONTATOS)
            .select("id,nome,telefone,time")
            .order("time")
            .limit(MAXIMO_CONTATOS)
            .execute()
        )
    except Exception as exc:
        raise RuntimeError(f"Erro ao buscar contatos no Supabase: {exc}") from exc

    contatos = resposta.data or []
    logging.info("%s contato(s) encontrado(s).", len(contatos))
    return contatos


def normalizar_telefone(telefone: Any) -> str:
    return re.sub(r"\D", "", str(telefone or ""))


def montar_mensagem(nome: str) -> str:
    return MODELO_MENSAGEM.format(nome=nome)


def enviar_mensagem_whatsapp(telefone: str, mensagem: str, modo_teste: bool) -> bool:
    if modo_teste:
        logging.info("[DRY_RUN] Mensagem para %s: %s", telefone, mensagem)
        return True

    id_instancia = obter_variavel_obrigatoria("ZAPI_INSTANCE_ID")
    token_instancia = obter_variavel_obrigatoria("ZAPI_TOKEN")
    token_cliente = obter_variavel_obrigatoria("ZAPI_CLIENT_TOKEN")

    url = f"https://api.z-api.io/instances/{id_instancia}/token/{token_instancia}/send-text"
    cabecalhos = {
        "Client-Token": token_cliente,
        "Content-Type": "application/json",
    }
    dados = {
        "phone": telefone,
        "message": mensagem,
    }

    try:
        resposta = requests.post(url, json=dados, headers=cabecalhos, timeout=20)
        resposta.raise_for_status()
    except requests.RequestException as exc:
        logging.error("Erro ao enviar mensagem pela Z-API para %s: %s", telefone, exc)
        return False

    logging.info("Mensagem enviada para %s.", telefone)
    return True


def processar_contatos(contatos: list[dict[str, Any]], modo_teste: bool) -> None:
    total_enviadas = 0

    for contato in contatos:
        id_contato = contato.get("id", "sem id")
        nome = str(contato.get("nome") or "").strip()
        telefone = normalizar_telefone(contato.get("telefone"))

        if not nome:
            logging.warning("Contato %s ignorado: nome vazio.", id_contato)
            continue

        if not telefone:
            logging.warning("Contato %s ignorado: telefone vazio.", id_contato)
            continue

        mensagem = montar_mensagem(nome)
        logging.info("Preparando mensagem para %s (%s).", nome, telefone)

        if enviar_mensagem_whatsapp(telefone, mensagem, modo_teste):
            total_enviadas += 1

    logging.info("Processo finalizado. Mensagens processadas com sucesso: %s.", total_enviadas)


def main() -> int:
    configurar_logs()
    load_dotenv()

    modo_teste = modo_teste_ativo()
    logging.info("Modo DRY_RUN: %s", "ativo" if modo_teste else "inativo")

    try:
        supabase = conectar_supabase()
        contatos = buscar_contatos(supabase)
        processar_contatos(contatos, modo_teste)
    except RuntimeError as exc:
        logging.error(exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
