import signal
import sys
import threading

from source.profiling import initialize_profiling, logger, profiler
from source.mutex import SafeProcessLock
from source.core.zmq import ZMQBroker

initialize_profiling()
shutdown_event = threading.Event()

def main():
    try:
        with SafeProcessLock("my_communicator"):
            logger.info("communicator start")
            broker = ZMQBroker()

            def shutdown_handler(sig, frame):
                print("\n[Broker] Shutting down...")
                broker.close()
                shutdown_event.set()
                sys.exit(0)

            signal.signal(signal.SIGINT, shutdown_handler)
            signal.signal(signal.SIGTERM, shutdown_handler)

            # Block main thread
            print("[Broker] Running. Press Ctrl+C to exit.")
            shutdown_event.wait() 

    except FileExistsError:
        logger.info("Collector はすでに起動中です。")
    except:
        raise

if __name__ == "__main__":
    main()