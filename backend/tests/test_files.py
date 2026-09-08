"""Testes de catalogação, tipo real, associação e segurança do ZIP."""

from __future__ import annotations

import io
import zipfile

import pytest

from app.config import settings
from app.models.schemas import ProcessingStatus
from app.parsers.whatsapp import parse_chat
from app.services.mime import detect_mime, type_for_mime
from app.services.timeline import build_timeline
from app.services.zip_service import ZipRejected, choose_main_txt, extract_zip


def _extract(zip_path, tmp_path, **overrides):
    config = settings.model_copy(update=overrides) if overrides else settings
    return extract_zip(zip_path, tmp_path / "extraido", config)


def test_extensao_correta_e_tipo_real(make_zip, tmp_path, sample_media):
    chat = "25/08/2026 10:52 - Sanchai: audio.opus (arquivo anexado)\n"
    zip_path = make_zip(chat, {"audio.opus": sample_media["audio.opus"]})
    extraction = _extract(zip_path, tmp_path)
    audio = next(item for item in extraction.files if item.name == "audio.opus")
    assert audio.detected_mime == "audio/ogg"
    assert type_for_mime(audio.detected_mime) == "audio"


def test_arquivo_sem_extensao_e_identificado_pelo_conteudo(make_zip, tmp_path, sample_media):
    chat = "25/08/2026 10:52 - Sanchai: anexo-sem-extensao (arquivo anexado)\n"
    zip_path = make_zip(chat, {"anexo-sem-extensao": sample_media["documento.pdf"]})
    extraction = _extract(zip_path, tmp_path)
    item = extraction.files[1] if extraction.files[0].name == "_chat.txt" else extraction.files[0]
    assert item.detected_mime == "application/pdf"


def test_mime_divergente_da_extensao_prevalece_o_conteudo(make_zip, tmp_path, sample_media):
    chat = "25/08/2026 11:18 - Sanchai: contrato-com-extensao-errada.jpg (arquivo anexado)\n"
    zip_path = make_zip(
        chat, {"contrato-com-extensao-errada.jpg": sample_media["contrato-com-extensao-errada.jpg"]}
    )
    extraction = _extract(zip_path, tmp_path)
    main_txt, _log = choose_main_txt(extraction.txt_candidates, tmp_path / "extraido")
    timeline = build_timeline(
        parse_chat(chat), extraction.files, tmp_path / "extraido", main_txt.relative_path
    )
    event = timeline.events[0]
    assert event.detected_mime == "application/pdf"
    assert event.type == "pdf"
    assert event.metadata["mime_mismatch"]["extension"] == "image/jpeg"


def test_arquivo_orfao_aparece_no_relatorio(make_zip, tmp_path, sample_media):
    chat = "25/08/2026 11:03 - Rui: imagem.jpg (arquivo anexado)\n"
    zip_path = make_zip(
        chat, {"imagem.jpg": sample_media["imagem.jpg"], "orfao.jpg": sample_media["orfao.jpg"]}
    )
    extraction = _extract(zip_path, tmp_path)
    main_txt, _ = choose_main_txt(extraction.txt_candidates, tmp_path / "extraido")
    timeline = build_timeline(
        parse_chat(chat), extraction.files, tmp_path / "extraido", main_txt.relative_path
    )
    assert timeline.inventory.orphan_files == 1
    assert timeline.inventory.orphan_names == ["orfao.jpg"]
    assert len(timeline.events) == 1  # o órfão não entra na conversa


def test_anexo_citado_e_ausente_fica_visivel_como_nao_associado(make_zip, tmp_path):
    chat = "25/08/2026 12:01 - Rui: nao-existe.pdf (arquivo anexado)\n"
    zip_path = make_zip(chat)
    extraction = _extract(zip_path, tmp_path)
    main_txt, _ = choose_main_txt(extraction.txt_candidates, tmp_path / "extraido")
    timeline = build_timeline(
        parse_chat(chat), extraction.files, tmp_path / "extraido", main_txt.relative_path
    )
    event = timeline.events[0]
    assert event.processing_status == ProcessingStatus.UNRESOLVED
    assert event.attachment_path is None
    assert timeline.inventory.attachments_unresolved == 1
    assert any(w.code == "unresolved_attachments" for w in timeline.warnings)


def test_associacao_ignora_diferenca_de_caixa_como_ultimo_recurso(make_zip, tmp_path, sample_media):
    chat = "25/08/2026 11:03 - Rui: IMAGEM.JPG (arquivo anexado)\n"
    zip_path = make_zip(chat, {"imagem.jpg": sample_media["imagem.jpg"]})
    extraction = _extract(zip_path, tmp_path)
    main_txt, _ = choose_main_txt(extraction.txt_candidates, tmp_path / "extraido")
    timeline = build_timeline(
        parse_chat(chat), extraction.files, tmp_path / "extraido", main_txt.relative_path
    )
    assert timeline.events[0].attachment_path is not None
    assert timeline.events[0].metadata["match_strategy"] == "casefold"


def test_zip_slip_e_recusado(tmp_path):
    zip_path = tmp_path / "malicioso.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("_chat.txt", "25/08/2026 10:00 - A: oi\n")
        archive.writestr("../../fora.txt", "conteúdo malicioso")
    with pytest.raises(ZipRejected) as excinfo:
        _extract(zip_path, tmp_path)
    assert excinfo.value.code == "path_traversal"
    assert not (tmp_path.parent / "fora.txt").exists()


def test_zip_bomb_e_recusado_pela_taxa_de_compressao(tmp_path):
    zip_path = tmp_path / "bomba.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("_chat.txt", "25/08/2026 10:00 - A: oi\n")
        archive.writestr("gigante.bin", b"\0" * (20 * 1024 * 1024))
    with pytest.raises(ZipRejected) as excinfo:
        _extract(zip_path, tmp_path, max_uncompressed_mb=10)
    assert excinfo.value.code in {"too_large_uncompressed", "suspicious_compression"}


def test_limite_de_quantidade_de_arquivos(tmp_path):
    zip_path = tmp_path / "muitos.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("_chat.txt", "25/08/2026 10:00 - A: oi\n")
        for index in range(20):
            archive.writestr(f"arquivo-{index}.txt", "x")
    with pytest.raises(ZipRejected) as excinfo:
        _extract(zip_path, tmp_path, max_files_per_zip=5)
    assert excinfo.value.code == "too_many_files"


def test_zip_invalido_da_erro_claro(tmp_path):
    zip_path = tmp_path / "quebrado.zip"
    zip_path.write_bytes(b"isto nao e um zip")
    with pytest.raises(ZipRejected) as excinfo:
        _extract(zip_path, tmp_path)
    assert excinfo.value.code == "invalid_zip"


def test_escolha_do_txt_principal_entre_varios(make_zip, tmp_path):
    chat = "\n".join(f"25/08/2026 10:{minuto:02d} - Rui: mensagem {minuto}" for minuto in range(30))
    zip_path = make_zip(chat, {"leia-me.txt": b"apenas um aviso sem timestamps"})
    extraction = _extract(zip_path, tmp_path)
    main_txt, log = choose_main_txt(extraction.txt_candidates, tmp_path / "extraido")
    assert main_txt.name == "_chat.txt"
    assert log[0]["timestamp_lines"] == 30


def test_zip_sem_txt_nao_tem_candidato(tmp_path, sample_media):
    zip_path = tmp_path / "sem-txt.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(sample_media["imagem.jpg"], "imagem.jpg")
    extraction = _extract(zip_path, tmp_path)
    main_txt, _ = choose_main_txt(extraction.txt_candidates, tmp_path / "extraido")
    assert main_txt is None


def test_deteccao_de_tipos_comuns(tmp_path):
    amostras = {
        "a.pdf": b"%PDF-1.7\n%...",
        "b.png": b"\x89PNG\r\n\x1a\n" + b"\0" * 20,
        "c.jpg": b"\xff\xd8\xff\xe0" + b"\0" * 20,
        "d.webp": b"RIFF\x00\x00\x00\x00WEBPVP8 ",
        "e.wav": b"RIFF\x00\x00\x00\x00WAVEfmt ",
        "f.mp4": b"\x00\x00\x00\x18ftypmp42" + b"\0" * 12,
        "g.ogg": b"OggS\x00\x02" + b"\0" * 20 + b"OpusHead",
        "h.mp3": b"ID3\x03\x00" + b"\0" * 20,
        "i.webm": b"\x1a\x45\xdf\xa3" + b"\0" * 20,
    }
    esperados = {
        "a.pdf": "application/pdf", "b.png": "image/png", "c.jpg": "image/jpeg",
        "d.webp": "image/webp", "e.wav": "audio/wav", "f.mp4": "video/mp4",
        "g.ogg": "audio/ogg", "h.mp3": "audio/mpeg", "i.webm": "video/webm",
    }
    for name, content in amostras.items():
        path = tmp_path / name
        path.write_bytes(content)
        assert detect_mime(path) == esperados[name], name


def test_arquivo_vazio_nao_quebra_deteccao(tmp_path):
    vazio = tmp_path / "vazio.bin"
    vazio.write_bytes(b"")
    assert detect_mime(vazio) is None


def test_leitura_de_txt_em_utf16(make_zip, tmp_path):
    chat = "25/08/2026 10:00 - Rui: acentuação preservada\n"
    zip_path = tmp_path / "utf16.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("_chat.txt", chat.encode("utf-16"))
    extraction = _extract(zip_path, tmp_path)
    from app.services.zip_service import read_text_file

    conteudo = read_text_file(tmp_path / "extraido" / extraction.files[0].relative_path)
    assert "acentuação preservada" in conteudo


def test_zip_em_memoria_nao_e_necessario(tmp_path, sample_media):
    """A extração é feita em disco, em streaming — sem carregar o ZIP inteiro."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("_chat.txt", "25/08/2026 10:00 - A: oi\n")
    zip_path = tmp_path / "streaming.zip"
    zip_path.write_bytes(buffer.getvalue())
    extraction = _extract(zip_path, tmp_path)
    assert extraction.total_uncompressed > 0
