resource "aws_ecs_cluster" "ecs_cluster" {
  name = "demo-bokeh-org"

}

resource "aws_ecs_capacity_provider" "cluster_capacity" {
  name = "demo"

  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.cluster_capacity.arn
    managed_termination_protection = "ENABLED"

    managed_scaling {
      instance_warmup_period    = 60
      maximum_scaling_step_size = 2
      minimum_scaling_step_size = 1
      status                    = "ENABLED"
      target_capacity           = 100
    }
  }
}

resource "aws_ecs_cluster_capacity_providers" "ecs_build_capacity_providers" {
  cluster_name = aws_ecs_cluster.ecs_cluster.name
  capacity_providers = [
    aws_ecs_capacity_provider.cluster_capacity.name
  ]
  default_capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.cluster_capacity.name
    weight            = 1
  }
  lifecycle {
    create_before_destroy = true
  }
}
