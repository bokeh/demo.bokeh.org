terraform {
  backend "s3" {
    bucket = "terraform-demo-bokeh-org"
    key    = "state.tfstate"
  }
}
