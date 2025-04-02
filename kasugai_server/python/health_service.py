from grpc_health.v1 import health_pb2, health_pb2_grpc
from server_logger import ServerLogger

class HealthService(health_pb2_grpc.HealthServicer):
    def __init__(self):
        self.logger = ServerLogger.get_logger("HealthService")
    
    def Check(self, request, context):
        self.logger.info("Health check requested.")
        # Always return SERVING; you could add logic here to change status based on internal metrics.
        return health_pb2.HealthCheckResponse(status=health_pb2.HealthCheckResponse.SERVING)
