# demo.bokeh.org

Hosted Bokeh App Demos

## Running Locally

### Setup

Clone this repository:
```
git clone https://github.com/bokeh/demo.bokeh.org.git
```
and [install Docker](https://docs.docker.com/install/) on your platform

### Building 

In the top level of this repository, execute the command
```
docker build --tag bokeh/demo.bokeh.org .
```

### Running

Execute the command to start the Docker container:
```
docker run --rm -p 5006:5006 -it bokeh/demo.bokeh.org
```
Now navigate to ``http://localhost:5006`` to interact with the demo site. 

## Deploying to AWS

The published [demo.bokeh.org](https://demo.bokeh.org) site is deployed using [Elastic Beanstalk with Docker Containers](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/create_deploy_docker.html). 

Random notes for future reference:

* Load balancer protocol needs to be set to TCP to allow websocket connections
* Similar rules needed to security group config
