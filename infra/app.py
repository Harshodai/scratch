#!/usr/bin/env python3
import os
import aws_cdk as cdk
from infra.centrag_stack import CentragStack

app = cdk.App()
CentragStack(app, "CentragStack",
    env=cdk.Environment(account=os.getenv('CDK_DEFAULT_ACCOUNT'), region=os.getenv('CDK_DEFAULT_REGION')),
)

app.synth()
