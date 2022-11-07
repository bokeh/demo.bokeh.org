resource "aws_security_group" "sg_demo_bokeh_org" {
  vpc_id = aws_vpc.vpc.id

  ingress {
    from_port   = 5006
    to_port     = 5006
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

}
