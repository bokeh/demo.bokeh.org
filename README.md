# demo.bokeh.org

Hosted Bokeh App Demos

***NOTE***: *The [demo.bokeh.org](https://demo.bokeh.org) site has moved to a simpler deployment based on Docker and Elastic AWS Beanstalk. To see the old Nginx/Salt based deployment code, look at the ``nginx_salt_deploy`` branch.*

## Using Locally

### Setup

Clone this repository:
```
git clone https://github.com/bokeh/demo.bokeh.org.git
```
and [install Docker](https://docs.docker.com/install/) on your platform

### Building 

In the top level of this repository, execute the command
```
docker build --tag demo.bokeh.org .
```

### Running

Execute the command to start the Docker container:
```
docker run --rm -p 5006:5006 -it demo.bokeh.org
```
Now navigate to ``http://localhost:5006`` to interact with the demo site. 

## Deploying to AWS

The published [demo.bokeh.org](https://demo.bokeh.org) site is deployed using [Ealstic Beanstalk with Docker Containers](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/create_deploy_docker.html). 

Random notes for future reference:

* Load balancer protocol needs to be set to TCP to allow websocket connections
* Similar rules needed to security group config
