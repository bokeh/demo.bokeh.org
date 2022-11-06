data "aws_ssm_parameter" "recommended_ecs_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2/recommended/image_id"
}

data "template_file" "user_data_hw" {
  template = <<EOF
#!/bin/bash
echo ECS_CLUSTER=${aws_ecs_cluster.ecs_cluster.name} >> /etc/ecs/ecs.config
EOF
}

data "aws_ami" "ecs_ami" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["amzn-ami-*-amazon-ecs-optimized"]
  }
}

resource "aws_launch_template" "ecs_launch_demo_bokeh_org" {
  name                                 = "demo-bokeh-org"
  disable_api_termination              = true
  image_id                             = data.aws_ssm_parameter.recommended_ecs_ami.value
  instance_initiated_shutdown_behavior = "terminate"
  instance_type                        = "m6i.large"
  vpc_security_group_ids               = [aws_security_group.sg_demo_bokeh_org.id]
  user_data                            = base64encode(data.template_file.user_data_hw.rendered)

  iam_instance_profile {
    name = aws_iam_instance_profile.ecs_agent.name
  }

}

resource "aws_autoscaling_group" "cluster_capacity" {
  name                = "asg"
  vpc_zone_identifier = [aws_subnet.pub_subnet.id]

  launch_template {
    id      = aws_launch_template.ecs_launch_demo_bokeh_org.id
    version = "$Latest"
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = ""
    propagate_at_launch = true
  }

  tag {
    key = "Environment"
    value = "demo"
    propagate_at_launch = true
  }

  tag {
    key = "Owner"
    value = "terraform"
    propagate_at_launch = true
  }

  tag {
    key = "Name"
    value = "demo-container-instance"
    propagate_at_launch = true
  }

  protect_from_scale_in     = true
  desired_capacity          = null
  min_size                  = 0
  max_size                  = 4
  health_check_grace_period = 300
  health_check_type         = "EC2"
}
