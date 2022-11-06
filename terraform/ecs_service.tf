resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.ecs_cluster.id
  task_definition = aws_ecs_task_definition.task_definition.arn
  desired_count   = 2

  capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.cluster_capacity.name
    weight            = 1
  }

  network_configuration {
    security_groups  = [aws_security_group.sg_demo_bokeh_org.id]
    subnets          = [aws_subnet.pub_subnet.id, aws_subnet.pub_subnet2.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.demo_bokeh_org_web.arn
    container_name   = "worker"
    container_port   = 5006
  }
}
