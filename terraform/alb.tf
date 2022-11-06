resource "aws_security_group" "sg_demo_bokeh_org_alb" {
  name   = "demo-bokeh-org-alb-web-access"
  vpc_id = aws_vpc.vpc.id

  ingress {
    description      = "TLS from internet"
    from_port        = 443
    to_port          = 443
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  ingress {
    description      = "HTTP from internet"
    from_port        = 80
    to_port          = 80
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb" "demo_bokeh_org_web_alb" {
  name                       = "demo-bokeh-org-alb"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.sg_demo_bokeh_org_alb.id]
  subnets                    = [aws_subnet.pub_subnet.id, aws_subnet.pub_subnet2.id]
  enable_deletion_protection = false
  idle_timeout               = 600
}


resource "aws_lb_target_group" "demo_bokeh_org_web" {
  name                          = "demo-bokeh-org-web-${substr(uuid(), 0, 3)}"
  port                          = 5006
  protocol                      = "HTTP"
  vpc_id                        = aws_vpc.vpc.id
  target_type                   = "ip"
  deregistration_delay          = 10
  load_balancing_algorithm_type = "round_robin"

  lifecycle {
    create_before_destroy = true
    ignore_changes        = [name]
    # https://github.com/terraform-providers/terraform-provider-aws/issues/636
  }

  health_check {
    enabled  = true
    interval = 60
    path     = "/"
  }
}

data "aws_acm_certificate" "issued" {
  domain   = "*.bokeh.org"
  statuses = ["ISSUED"]
}

resource "aws_lb_listener" "demo_bokeh_org_web" {
  load_balancer_arn = aws_lb.demo_bokeh_org_web_alb.arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS-1-2-Ext-2018-06" # requires tls 1.2 or higher
  certificate_arn   = data.aws_acm_certificate.issued.arn

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Access denied."
      status_code  = "403"
    }
  }
}

resource "aws_lb_listener_rule" "static" {
  listener_arn = aws_lb_listener.demo_bokeh_org_web.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.demo_bokeh_org_web.arn
  }

  condition {
    path_pattern {
      values = ["/*"]
    }
  }
}

resource "aws_lb_listener" "demo_bokeh_org_web_redirect" {
  load_balancer_arn = aws_lb.demo_bokeh_org_web_alb.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
