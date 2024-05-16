# demo.bokeh.org

*Under Construction*

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
