"""Separate trusted dispatcher process: python -m services.ingestion.dispatcher."""

import logging
import time

from services.ingestion.jobs import dispatch_pending, recover_queued

log = logging.getLogger("somaloom.ingestion")


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            delivery = dispatch_pending()
            recovery = recover_queued()
            if delivery or recovery:
                log.info("ingestion dispatcher scheduled=%d recovered=%d", delivery, recovery)
        except Exception:
            log.exception("Ingestion dispatcher cycle failed")
        time.sleep(10)


if __name__ == "__main__":
    main()
