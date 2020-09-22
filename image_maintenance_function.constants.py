import json
import os

# ? ENV setup from Lambda function ENV
BASE_IMAGE_NAME = os.environ.get("base_image_name")
SUBNET_ID = os.environ.get("subnet_id")
SECURITY_GROUPS = json.loads(os.environ.get("security_groups"))
KEY_GROUP = os.environ.get("key_group")
INSTANCE_TYPE = os.environ.get("instance_type")
USERDATA = """#!/bin/bash
sudo yum --security update -y"""
IAM_ROLE = os.environ.get("iam_role")
LAUNCHCONFIG_NAMES = json.loads(os.environ.get("launchconfigs"))
CONFIG_GROUPS = json.loads(os.environ.get("config_groups"))
