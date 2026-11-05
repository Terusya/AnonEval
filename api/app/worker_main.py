import json
import logging
import signal
import time

import pika

from app.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("survey.summary_worker")


def main() -> None:
    settings = get_settings()
    while True:
        connection = None
        try:
            connection = pika.BlockingConnection(pika.URLParameters(settings.rabbitmq_url))
            channel = connection.channel()
            channel.queue_declare(queue="summary_tasks", durable=True)
            channel.basic_qos(prefetch_count=1)

            def handle_message(ch, method, properties, body) -> None:
                try:
                    event = json.loads(body)
                    logger.info(
                        "Summary generation is disabled; acknowledged event_id=%s survey_id=%s",
                        event.get("event_id"),
                        event.get("survey_id"),
                    )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except (ValueError, TypeError):
                    logger.exception("Invalid summary task; rejecting without requeue")
                    ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)

            channel.basic_consume(queue="summary_tasks", on_message_callback=handle_message)
            logger.info("Summary stub worker is listening")
            channel.start_consuming()
        except (pika.exceptions.AMQPError, OSError):
            logger.exception("Broker unavailable; retrying shortly")
            time.sleep(3)
        finally:
            if connection is not None and connection.is_open:
                connection.close()


if __name__ == "__main__":
    main()
