FROM continuumio/miniconda
LABEL org.bokeh.demo.maintainer="Bokeh <info@bokeh.org>"

ENV BK_VERSION=3.0.1
ENV PY_VERSION=3.10
ENV BOKEH_RESOURCES=cdn
ENV BOKEH_LOG_LEVEL=debug

RUN apt-get install git bash

RUN git clone --depth 1 --branch $BK_VERSION https://github.com/bokeh/bokeh.git /bokeh

RUN mkdir -p /examples && cp -r /bokeh/examples/server/app /examples/ && rm -rf /bokeh

RUN conda install -c bokeh --yes --quiet python=${PY_VERSION} pyyaml jinja2 bokeh=${BK_VERSION} numpy "nodejs>=14" pandas scipy
RUN conda clean -ay

RUN python -c 'import bokeh; bokeh.sampledata.download(progress=False)'

ADD https://raw.githubusercontent.com/bokeh/demo.bokeh.org/main/index.html /index.html

EXPOSE 5006

CMD bokeh serve \
    --index=/index.html \
    --allow-websocket-origin="*" \
    --log-level=${BOKEH_LOG_LEVEL} \
    /examples/app/crossfilter \
    /examples/app/export_csv \
    /examples/app/gapminder \
    /examples/app/movies \
    /examples/app/selection_histogram.py \
    /examples/app/sliders.py \
    /examples/app/surface3d \
    /examples/app/population.py \
    /examples/app/weather
