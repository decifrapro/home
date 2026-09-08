"""Conversão dos modelos internos para o JSON que o frontend consome."""

from __future__ import annotations

from app.models.schemas import Event, Job, LinkItem
from app.services.naming import camelize


def link_to_dict(link: LinkItem) -> dict:
    return {
        "id": link.id,
        "eventId": link.event_id,
        "url": link.url,
        "status": link.status.value,
        "title": link.title,
        "description": link.description,
        "content": link.content,
        "error": link.error,
    }


def event_to_dict(event: Event) -> dict:
    metadata = event.metadata or {}
    return {
        "id": event.id,
        "index": event.index,
        "rawTimestamp": event.raw_timestamp,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "sender": event.sender,
        "type": event.type.value,
        "rawText": event.raw_text,
        "caption": event.caption,
        "attachmentName": event.attachment_name,
        "detectedMime": event.detected_mime,
        "processedText": event.processed_text,
        "processingStatus": event.processing_status.value,
        "processingError": event.processing_error,
        "metadata": {
            "durationSeconds": metadata.get("duration_seconds"),
            "pagesCount": metadata.get("pages_count"),
            "frames": metadata.get("frames"),
            "fileSize": metadata.get("file_size"),
            "ocrText": metadata.get("ocr_text"),
            "visualDescription": metadata.get("visual_description"),
            "transcript": metadata.get("transcript"),
            "pages": metadata.get("pages"),
            "mimeMismatch": metadata.get("mime_mismatch"),
            "mediaOmitted": metadata.get("media_omitted"),
            "edited": metadata.get("edited"),
            "forwarded": metadata.get("forwarded"),
            "deleted": metadata.get("deleted"),
        },
        "links": [link_to_dict(link) for link in event.links],
    }


def job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "status": job.status.value,
        "createdAt": job.created_at.isoformat() if job.created_at else None,
        "updatedAt": job.updated_at.isoformat() if job.updated_at else None,
        "originalFilename": job.original_filename,
        "zipSize": job.zip_size,
        "error": job.error,
        "warnings": [warning.model_dump() for warning in job.warnings],
        "inventory": camelize(job.inventory.model_dump()),
        "coverage": {
            "categories": {
                name: {**bucket.model_dump(), "complete": bucket.complete}
                for name, bucket in job.coverage.categories.items()
            },
            "overallTotal": job.coverage.overall_total,
            "overallDone": job.coverage.overall_done,
            "percent": job.coverage.percent,
            "complete": job.coverage.complete,
        },
        "estimate": job.estimate.model_dump() if job.estimate else None,
        "cost": {**job.cost.model_dump(), "totalUsd": job.cost.total_usd},
        "confirmed": job.confirmed,
        "conversationStart": job.conversation_start.isoformat() if job.conversation_start else None,
        "conversationEnd": job.conversation_end.isoformat() if job.conversation_end else None,
        "eventCount": job.event_count,
        "metadata": job.metadata,
        "schemaVersion": job.schema_version,
    }
