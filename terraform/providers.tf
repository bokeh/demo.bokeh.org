provider "aws" {
  default_tags {
    tags = {
      Environment = "demo"
      Owner       = "terraform"
    }
  }
}
