import asyncio
import threading
from src.global_logger import GlobalLogger

class MessageProcessor:
    """
    Processes incoming chat messages using an asyncio queue,
    batching them for efficient socket emission and database writes.
    """
    def __init__(self, socketio, chat_history, batch_size=10, flush_interval=1.0):
        self.logger = GlobalLogger.get_logger("MessageProcessor")
        self.socketio = socketio
        self.chat_history = chat_history
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        # Create a new asyncio event loop for message processing
        self.loop = asyncio.new_event_loop()
        self.queue = asyncio.Queue(loop=self.loop)

        # Start the loop in a background thread
        threading.Thread(target=self._start_loop, daemon=True).start()

    def _start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._process_messages())

    async def _process_messages(self):
        while True:
            batch = []
            try:
                # Wait for at least one message or timeout
                msg = await asyncio.wait_for(self.queue.get(), timeout=self.flush_interval)
                batch.append(msg)

                # Collect up to batch_size messages without waiting
                for _ in range(self.batch_size - 1):
                    try:
                        m = self.queue.get_nowait()
                        batch.append(m)
                    except asyncio.QueueEmpty:
                        break
            except asyncio.TimeoutError:
                # No messages arrived in this interval, proceed with whatever we have
                pass

            # Process the batch
            for message in batch:
                try:
                    # Emit to connected clients
                    self.socketio.emit('new_message', {
                        'sender': message.senderId.uuid,
                        'content': message.content
                    })
                    # Persist to database
                    self.chat_history.add_message(
                        name=message.senderId.uuid,
                        message=message.content,
                        time=str(message.timestamp.ToDatetime())
                    )
                    self.logger.info(f"Processed message from {message.senderId.uuid}")
                except Exception as e:
                    self.logger.error(f"Error processing message: {e}")
