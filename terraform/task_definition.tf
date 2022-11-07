locals {
  task = {
    "essential" : true,
    "memory" : 1024,
    "name" : "worker",
    "cpu" : 2,
    "image" : "bokeh/demo.bokeh.org:latest",
    "environment" : [

    ]
    portMappings = [
      {
        hostPort      = 5006
        protocol      = "tcp"
        containerPort = 5006
      }
    ]
  }
}

resource "aws_ecs_task_definition" "task_definition" {
  family                = "worker"
  container_definitions = jsonencode([local.task])
  network_mode          = "awsvpc"
}
