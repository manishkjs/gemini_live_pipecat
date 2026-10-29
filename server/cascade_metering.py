"""Small provider-boundary helpers; pricing never changes generated audio/text."""
from cascade_pricing import metadata_dict


async def publish_cost(service):
    meter = getattr(service, "_cascade_meter", None)
    if meter is None:
        return
    from loguru import logger
    from pipecat.frames.frames import OutputTransportMessageUrgentFrame as OutputTransportMessageFrame
    try:
        await service.push_frame(OutputTransportMessageFrame(message={
            "label": "rtvi-ai", "type": "server-message",
            "data": {"type": "metrics", "payload": meter.snapshot()},
        }))
    except Exception as exc:
        logger.warning("Cascade cost telemetry could not be delivered: {}", type(exc).__name__)


def observe_tokens(meter, key, metadata):
    usage = metadata_dict(metadata)
    if usage:
        meter.update(key, usage=usage)
        from loguru import logger
        # Usage metadata has only counters/modalities; do not log prompts/keys.
        logger.info("Cascade usage session={} request={} stage={} model={} usage={}",
                    meter.session_id, key, meter.records[key]["stage"], meter.records[key]["model"], usage)


def billed_duration(metadata):
    """Cloud Speech reports a request total; an absent duration is not zero."""
    if metadata is None:
        return None
    pb = getattr(metadata, "_pb", metadata)
    if hasattr(pb, "HasField") and not pb.HasField("total_billed_duration"):
        return None
    value = getattr(metadata, "total_billed_duration", None)
    if value is None:
        return None
    if hasattr(value, "total_seconds"):
        return value.total_seconds()
    if hasattr(value, "seconds"):
        return value.seconds + getattr(value, "nanos", 0) / 1_000_000_000
    return None
