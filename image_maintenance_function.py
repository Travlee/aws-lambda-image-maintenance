# ? AWS Lambda Function - image_maintenance_function

import json
import boto3
import pprint
import re
import datetime
import os
import base64
import constants


def lambda_handler(event, context):

    # ? 1. Get AMI ID
    ami_info = get_ami_id_by_name(constants.BASE_IMAGE_NAME + "*")
    # ! DEBUGINFO
    print("USING " + ami_info["Name"] + " AS BASEIMAGE")

    # ? 2. Run instance with ami_id and userdata w. yum update -y
    instance_id = run_instance(
        ami_info["ImageId"],
        constants.SUBNET_ID,
        constants.SECURITY_GROUPS,
        constants.KEY_GROUP,
        constants.BASE_IMAGE_NAME,
        constants.INSTANCE_TYPE,
        constants.USERDATA
    )

    # ? 3. Create image of instance, once userdata has completed, then terminate instance
    instance_ready = get_instance_ready(instance_id)
    if(instance_ready is not True):
        return {'statusCode': 200, 'body': json.dumps('Instance initialzation error')}
    new_image_name = constants.BASE_IMAGE_NAME + \
        "-" + datetime.date.today().strftime("%d%b%y")
    created_ami_id = create_image(instance_id, new_image_name)
    terminate_instance(instance_id)
    # ! DEBUGINFO
    print("NEW BASE IMAGE AS " + new_image_name)

    # ? 4. Create new launchconfig and update autoscaling group; restat instances
    launchconfigs = get_all_launchconfigs()
    autoscalings = get_all_autoscaling()
    for group in constants.CONFIG_GROUPS:
        launchconfig = filter_launchconfigs(
            launchconfigs, group["LaunchConfig"])
        autoscaling = filter_autoscalings(autoscalings, group["AutoScaling"])
        new_launchconfig_name = create_launchconfig(
            launchconfig, created_ami_id)
        if new_launchconfig_name != False:
            update_autoscaling(
                autoscaling["AutoScalingGroupName"], new_launchconfig_name)
            restart_autoscaling_instances(autoscaling)
            # ! DEBUGINFO
            print("NEW LAUNCHCONFIG AS " + new_launchconfig_name)

    # ? 5. Clean up old ami and launchconfig??
    # result_ami_delete = delete_ami_by_id(ami_info["ImageId"])

    return {'statusCode': 200, 'body': json.dumps('Image Maintenance Lambda Completed')}


def create_image(instance_id, ami_name):
    assert len(instance_id) != 0
    assert len(ami_name) != 0

    ec2 = boto3.client('ec2')

    response = ec2.create_image(
        Description='',
        DryRun=False,
        InstanceId=instance_id,
        Name=ami_name,
        NoReboot=False
    )
    return response["ImageId"]


def get_image_count(ami_name):
    assert len(ami_name) != 0

    result = re.match(r".*image([0-9]+)", ami_name)
    return int(result.group(1)) + 1


def get_instance_info(instance_id="", request_filter=[]):

    ec2 = boto3.client('ec2')

    response = ec2.describe_instances(
        Filters=request_filter,
        InstanceIds=[instance_id] if instance_id is not None and len(
            instance_id) != 0 else [],
    )

    return response["Reservations"][0]["Instances"][0]


def get_instance_ready(instance_id):
    try:
        ec2 = boto3.client('ec2')
        waiter = ec2.get_waiter('instance_status_ok')
        waiter.wait(InstanceIds=[instance_id])
        return True
    except Exception:
        return False


def create_launchconfig(config, image_id):
    try:
        client = boto3.client('autoscaling')
        new_launchconfig_name = config["FilterName"] + \
            "-" + datetime.date.today().strftime("%d%b%y")

        response = client.create_launch_configuration(
            LaunchConfigurationName=new_launchconfig_name,
            ImageId=image_id,
            KeyName=config["KeyName"],
            SecurityGroups=config["SecurityGroups"],
            UserData=config["UserData"],
            InstanceType=config["InstanceType"],
            InstanceMonitoring={
                'Enabled': False
            },
            IamInstanceProfile=config["IamInstanceProfile"],
        )
        return new_launchconfig_name
    except Exception as ex:
        print(ex)
        return False


def update_autoscaling(autoscaling_group_name, launchconfig_name):

    try:
        client = boto3.client('autoscaling')
        response = client.update_auto_scaling_group(
            AutoScalingGroupName=autoscaling_group_name,
            LaunchConfigurationName=launchconfig_name,
        )
        return response
    except Exception:
        return False


def get_all_launchconfigs():

    # ? Response Structure
    # {"LaunchConfigurations": [
    # ['LaunchConfigurationName',
    #   'LaunchConfigurationARN',
    #   'ImageId',
    #   'KeyName',
    #   'SecurityGroups',
    #   'ClassicLinkVPCSecurityGroups',
    #   'UserData',
    #   'InstanceType',
    #   'KernelId',
    #   'RamdiskId',
    #   'BlockDeviceMappings',
    #   'InstanceMonitoring',
    #   'IamInstanceProfile',
    #   'CreatedTime',
    #   'EbsOptimized']
    # ]}

    try:
        client = boto3.client('autoscaling')
        response = client.describe_launch_configurations(
            LaunchConfigurationNames=[],
        )
        return response["LaunchConfigurations"]
    except Exception as ex:
        print(ex)
        return False


def get_all_autoscaling():

    try:
        client = boto3.client('autoscaling')
        response = client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[],
        )
        return response["AutoScalingGroups"]
    except Exception as ex:
        print(ex)
        return False


def restart_autoscaling_instances(config):
    try:
        client = boto3.client('autoscaling')
        for instance in config["Instances"]:
            response = client.terminate_instance_in_auto_scaling_group(
                InstanceId=instance["InstanceId"],
                ShouldDecrementDesiredCapacity=True
            )
            return True
    except Exception as ex:
        print(ex)
        return False


# ? Filters
def filter_launchconfigs(configs, filter):
    latest = None
    for config in configs:
        if filter in config["LaunchConfigurationName"]:
            if latest is None or config["CreatedTime"] >= latest["CreatedTime"]:
                config["UserData"] = base64.b64decode(config["UserData"])
                config["FilterName"] = filter
                latest = config
    return latest


def filter_autoscalings(configs, filter):
    latest = None
    for config in configs:
        if filter in config["AutoScalingGroupName"]:
            if latest is None or config["CreatedTime"] >= latest["CreatedTime"]:
                config["FilterName"] = filter
                latest = config
    return latest

# ? Returns the latest imageid for ami by name


def get_ami_id_by_name(ami_name):
    assert len(ami_name) != 0

    ec2 = boto3.client('ec2')

    response = ec2.describe_images(
        Filters=[
            {
                'Name': 'name',
                'Values': [
                    ami_name,
                ]
            },
        ],
        Owners=['self'],
        DryRun=False
    )

    latest = None
    for image in response["Images"]:
        if(latest == None or image["CreationDate"] > latest["CreationDate"]):
            latest = image

    return {"ImageId": latest["ImageId"], "Name": latest["Name"]}


def delete_ami_by_id(ami_id):
    assert len(ami_id) != 0

    ec2 = boto3.client('ec2')

    response = ec2.deregister_image(
        ImageId=ami_id,
        DryRun=False
    )
    # print(response)

    return True


def run_instance(image_id, subnet_id, security_group_ids, key, tag_name, instance_type="t3.small", userdata="", region="us-gov-west-1"):
    assert len(image_id) != 0
    assert len(subnet_id) != 0
    assert len(security_group_ids) != 0
    # assert type(security_group_ids) === "array"
    assert len(key) != 0
    assert len(tag_name) != 0
    assert len(instance_type) != 0
    assert len(region) != 0

    ec2 = boto3.client('ec2')

    response = ec2.run_instances(
        ImageId=image_id,
        InstanceType=instance_type,
        KeyName=key,
        MaxCount=1,
        MinCount=1,
        SecurityGroupIds=security_group_ids,
        SubnetId=subnet_id,
        UserData=userdata,
        DryRun=False,
        InstanceInitiatedShutdownBehavior='terminate',
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': [
                    {
                        'Key': 'Name',
                        'Value': tag_name
                    },
                ]
            },
        ],
    )
    return response["Instances"][0]["InstanceId"]


def terminate_instance(instance_id):
    try:
        ec2 = boto3.client('ec2')
        response = ec2.terminate_instances(
            InstanceIds=[
                instance_id,
            ],
            DryRun=False
        )
        # print(response)
        return True
    except Exception as ex:
        print(ex)
        return False

# ? Get instance id by instance_name


def get_instance_id_by_name(instance_name):

    instance_info = get_instance_info(None,
                                      [
                                          {
                                              'Name': 'tag:Name',
                                              'Values': [
                                                  instance_name
                                              ]
                                          },
                                      ]
                                      )
    return instance_info["InstanceId"]
