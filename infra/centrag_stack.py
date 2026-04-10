from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
)
from constructs import Construct

class CentragStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 1. VPC across 3 Availability Zones (ADR-007 compliant)
        vpc = ec2.Vpc(self, "CentragVpc", max_azs=3)

        # 2. ECS Cluster
        cluster = ecs.Cluster(self, "CentragCluster", vpc=vpc)

        # 3. Application Load Balanced Fargate Service
        # (References the newly scaffolded Dockerfile in root)
        self.fastapi_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "CentragApiService",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=3,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(".."),
                container_port=8000
            ),
            public_load_balancer=True
        )
