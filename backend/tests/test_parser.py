"""Testes do parser: as variações reais das exportações do WhatsApp."""

from __future__ import annotations

from app.parsers.whatsapp import extract_urls, infer_date_order, parse_chat


def test_formato_android_portugues():
    result = parse_chat("25/08/2026 10:52 - Sanchai: mensagem simples\n")
    event = result.events[0]
    assert event.sender == "Sanchai"
    assert event.raw_text == "mensagem simples"
    assert event.timestamp.isoformat() == "2026-08-25T10:52:00"
    assert event.type == "text"


def test_formato_ios_com_colchetes_e_12h():
    result = parse_chat("[6/15/26, 10:05:38 AM] Isabela: mensagem iOS\n")
    event = result.events[0]
    assert event.sender == "Isabela"
    assert result.date_order == "mdy"
    assert event.timestamp.isoformat() == "2026-06-15T10:05:38"


def test_relogio_12h_pm_vira_24h():
    result = parse_chat("[15/06/2026, 10:05:38 PM] Rui: boa noite\n")
    assert result.events[0].timestamp.hour == 22


def test_relogio_24h():
    result = parse_chat("15/06/2026 22:05 - Rui: boa noite\n")
    assert result.events[0].timestamp.hour == 22


def test_mensagem_multilinha_nao_fragmenta():
    chat = (
        "25/08/2026 10:45 - Sanchai: primeira linha\n"
        "segunda linha\n"
        "terceira linha\n"
        "25/08/2026 10:46 - Rui: outra mensagem\n"
    )
    result = parse_chat(chat)
    assert len(result.events) == 2
    assert result.events[0].raw_text == "primeira linha\nsegunda linha\nterceira linha"


def test_emojis_e_acentos_preservados():
    result = parse_chat("25/08/2026 10:45 - João Antônio: tudo certo 👍🏽 é isso aí\n")
    assert result.events[0].sender == "João Antônio"
    assert result.events[0].raw_text == "tudo certo 👍🏽 é isso aí"


def test_mensagem_editada_marcada():
    result = parse_chat("25/08/2026 10:45 - Rui: perfeito <Esta mensagem foi editada>\n")
    assert result.events[0].metadata.get("edited") is True


def test_mensagem_encaminhada_marcada():
    result = parse_chat("25/08/2026 10:45 - Rui: Encaminhada muitas vezes: veja isso\n")
    assert result.events[0].metadata.get("forwarded") is True


def test_duas_mensagens_no_mesmo_horario_mantem_ordem():
    chat = (
        "25/08/2026 10:45 - Sanchai: primeira\n"
        "25/08/2026 10:45 - Rui: segunda\n"
        "25/08/2026 10:45 - Sanchai: terceira\n"
    )
    result = parse_chat(chat)
    assert [event.index for event in result.events] == [0, 1, 2]
    assert [event.raw_text for event in result.events] == ["primeira", "segunda", "terceira"]
    assert len({event.timestamp for event in result.events}) == 1


def test_legenda_associada_ao_anexo_android():
    chat = "25/08/2026 11:03 - Rui: IMG-20260825-WA0010.jpg (arquivo anexado)\nOlha essa condição\n"
    event = parse_chat(chat).events[0]
    assert event.attachment_name == "IMG-20260825-WA0010.jpg"
    assert event.caption == "Olha essa condição"
    assert event.type == "image"


def test_anexo_ios_com_legenda():
    chat = "[25/08/2026, 11:03:00] Rui: ‎<anexado: 00000042-PHOTO.jpg>\nOlha essa condição\n"
    event = parse_chat(chat).events[0]
    assert event.attachment_name == "00000042-PHOTO.jpg"
    assert event.caption == "Olha essa condição"


def test_nome_de_arquivo_com_espacos():
    chat = "25/08/2026 11:10 - Sanchai: Proposta Sala 705.pdf (arquivo anexado)\n"
    event = parse_chat(chat).events[0]
    assert event.attachment_name == "Proposta Sala 705.pdf"
    assert event.type == "pdf"


def test_url_dentro_da_mensagem_vira_subitem():
    chat = "25/08/2026 11:30 - Rui: dá uma olhada em https://exemplo.com/proposta.\n"
    event = parse_chat(chat).events[0]
    assert event.urls == ["https://exemplo.com/proposta"]
    assert event.type == "text"
    assert event.raw_text.endswith("proposta.")


def test_mensagem_so_com_url_vira_evento_de_link():
    event = parse_chat("25/08/2026 11:30 - Rui: https://exemplo.com/x\n").events[0]
    assert event.type == "link"
    assert event.urls == ["https://exemplo.com/x"]


def test_exportacao_sem_midia_avisa_com_clareza():
    chat = (
        "25/08/2026 10:45 - Rui: <Mídia oculta>\n"
        "25/08/2026 10:46 - Rui: <Mídia oculta>\n"
    )
    result = parse_chat(chat)
    assert result.media_omitted_count == 2
    aviso = next(w for w in result.warnings if w["code"] == "media_omitted")
    assert "Incluir mídia" in aviso["message"]
    assert all(event.metadata.get("media_omitted") for event in result.events)


def test_media_ocultada_ios_identifica_o_tipo():
    result = parse_chat("[25/08/2026, 10:45:00] Rui: ‎imagem ocultada\n")
    assert result.events[0].type == "image"
    assert result.events[0].metadata["media_omitted"] is True


def test_mensagem_de_sistema_nao_vira_remetente():
    chat = "25/08/2026 10:40 - As mensagens e as chamadas são criptografadas de ponta a ponta.\n"
    event = parse_chat(chat).events[0]
    assert event.type == "system"
    assert event.sender is None


def test_caracteres_invisiveis_nao_quebram_o_cabecalho():
    chat = "‎25/08/2026 10:45 - Sanchai: com marca invisível\n"
    assert parse_chat(chat).events[0].sender == "Sanchai"


def test_exportacao_truncada_registra_aviso():
    result = parse_chat("25/08/2026 10:45 - Sanchai: começo cortado\n")
    assert result.looks_truncated is True
    assert any(w["code"] == "truncated_export" for w in result.warnings)


def test_ordem_de_data_ambigua_assume_dia_primeiro():
    assert infer_date_order(["05/06/2026", "07/06/2026"]) == "dmy"
    assert infer_date_order(["25/08/2026"]) == "dmy"
    assert infer_date_order(["6/15/26"]) == "mdy"


def test_extracao_de_urls_remove_pontuacao_final():
    assert extract_urls("veja https://a.com/b, e www.c.com.") == ["https://a.com/b", "www.c.com"]
