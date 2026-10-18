"""Resumo diario para estudante de Processos Quimicos (Fatec Praia Grande, SP).

Busca noticias no Google News (RSS), pede para o Gemini escolher o que
importa e envia o resultado no Telegram.
"""
import os
import sys
import datetime
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

GEMINI_KEY = os.environ["GEMINI_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

PERFIL = (
    "Estudante do 2o semestre de Tecnologia em Processos Quimicos na Fatec "
    "Praia Grande (SP), morando na Baixada Santista. Busca a primeira "
    "oportunidade na area (industria ou pesquisa), iniciacao cientifica, "
    "cursos online gratuitos e novidades relevantes."
)

# Cada busca usa "when:7d" para trazer so os ultimos 7 dias.
BUSCAS = {
    "VAGAS E ESTAGIOS": [
        "estagio quimica Baixada Santista when:7d",
        "vaga tecnico quimico Cubatao when:7d",
        "estagio processos quimicos Sao Paulo when:7d",
        "vaga industria quimica estagio tecnologo when:7d",
    ],
    "INICIACAO CIENTIFICA E PESQUISA": [
        "iniciacao cientifica quimica edital when:14d",
        "bolsa iniciacao cientifica inscricoes CNPq FAPESP when:14d",
        "iniciacao cientifica Fatec Centro Paula Souza when:14d",
    ],
    "CURSOS ONLINE GRATUITOS": [
        "curso online gratuito quimica when:14d",
        "curso gratuito industria quimica seguranca processos when:14d",
        "curso gratuito Excel Python para engenharia when:14d",
    ],
    "NOTICIAS DA AREA": [
        "industria quimica Brasil when:7d",
        "quimica verde pesquisa when:7d",
        "Abiquim when:7d",
    ],
}

LINKS_FIXOS = """LINKS PARA CONSULTAR SEMPRE
- Estagios: https://www.ciee.org.br | https://www.linkedin.com/jobs | https://br.indeed.com | https://www.gupy.io
- Pesquisa: https://fapesp.br | https://www.gov.br/cnpq
- Cursos gratuitos: https://www.ev.org.br | https://www.coursera.org
- Dica: pergunte na coordenacao da Fatec sobre estagio e iniciacao cientifica."""


def buscar_noticias(consulta, limite=8):
    url = (
        "https://news.google.com/rss/search?q="
        + quote(consulta)
        + "&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    )
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        raiz = ET.fromstring(resp.content)
    except Exception as erro:  # noqa: BLE001
        print(f"Falha na busca '{consulta}': {erro}", file=sys.stderr)
        return []
    itens = []
    for item in raiz.iter("item"):
        itens.append(
            {
                "titulo": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "data": (item.findtext("pubDate") or "").strip(),
            }
        )
        if len(itens) >= limite:
            break
    return itens


def coletar():
    resultado = {}
    for secao, consultas in BUSCAS.items():
        vistos, lista = set(), []
        for consulta in consultas:
            for noticia in buscar_noticias(consulta):
                if noticia["titulo"] and noticia["titulo"] not in vistos:
                    vistos.add(noticia["titulo"])
                    lista.append(noticia)
        resultado[secao] = lista
    return resultado


def montar_prompt(dados):
    blocos = []
    for secao, lista in dados.items():
        linhas = [f"## {secao}"]
        for n in lista:
            linhas.append(f"- {n['titulo']} | {n['link']} | {n['data']}")
        if not lista:
            linhas.append("(nenhum resultado)")
        blocos.append("\n".join(linhas))
    material = "\n\n".join(blocos)
    return f"""Voce e o assistente pessoal de um estudante. Perfil: {PERFIL}

Abaixo estao resultados de busca de noticias, agrupados por secao. Monte o
resumo de hoje em portugues do Brasil, curto e direto, para ler no celular.

Regras:
- Use SOMENTE itens e links que aparecem na lista. Nunca invente vaga, curso, edital ou link.
- Escolha no maximo 4 itens por secao, so os realmente uteis para o perfil. Descarte o irrelevante.
- Cada item: uma linha com o titulo resumido e, na linha de baixo, o link.
- Se uma secao nao tiver nada util, escreva "Nada relevante hoje."
- Mantenha os titulos das secoes em MAIUSCULAS, sem markdown, sem asteriscos.
- Se um item parecer vaga fora de Sao Paulo ou sem relacao com quimica, descarte.

{material}
"""


def resumir_com_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    corpo = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(
        url,
        headers={"x-goog-api-key": GEMINI_KEY, "Content-Type": "application/json"},
        json=corpo,
        timeout=120,
    )
    resp.raise_for_status()
    dados = resp.json()
    return dados["candidates"][0]["content"]["parts"][0]["text"].strip()


def resumo_simples(dados):
    """Plano B caso o Gemini falhe: lista os titulos sem curadoria."""
    partes = []
    for secao, lista in dados.items():
        partes.append(secao)
        for n in lista[:4]:
            partes.append(f"{n['titulo']}\n{n['link']}")
        if not lista:
            partes.append("Nada encontrado.")
        partes.append("")
    return "\n".join(partes)


def enviar_telegram(texto, tamanho=3800):
    pedacos, atual = [], ""
    for linha in texto.split("\n"):
        if len(atual) + len(linha) + 1 > tamanho:
            pedacos.append(atual)
            atual = ""
        atual += linha + "\n"
    if atual.strip():
        pedacos.append(atual)
    for pedaco in pedacos:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": pedaco,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        resp.raise_for_status()


def main():
    hoje = datetime.date.today().strftime("%d/%m/%Y")
    dados = coletar()
    try:
        corpo = resumir_com_gemini(montar_prompt(dados))
    except Exception as erro:  # noqa: BLE001
        print(f"Gemini falhou: {erro}", file=sys.stderr)
        corpo = "(Curadoria automatica indisponivel hoje, segue a lista bruta.)\n\n" + resumo_simples(dados)
    enviar_telegram(f"BOM DIA! Resumo de {hoje}\n\n{corpo}\n\n{LINKS_FIXOS}")


if __name__ == "__main__":
    main()
              
