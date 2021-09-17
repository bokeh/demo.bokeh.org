FROM continuumio/miniconda
LABEL org.bokeh.demo.maintainer="Bokeh <info@bokeh.org>"

ENV BK_VERSION=2.4.0
ENV PY_VERSION=3.9
ENV NUM_PROCS=2
ENV BOKEH_RESOURCES=cdn
ENV BOKEH_LOG_LEVEL=debug

RUN apt-get install git bash

RUN git clone --branch $BK_VERSION https://github.com/bokeh/bokeh.git /bokeh

RUN mkdir -p /examples && cp -r /bokeh/examples/app /examples/ && rm -rf /bokeh

RUN conda config --append channels bokeh
RUN conda install --yes --quiet python=${PY_VERSION} pyyaml jinja2 bokeh=${BK_VERSION} numpy "nodejs>=8.8" pandas scipy
RUN conda clean -ay

RUN python -c 'import bokeh; bokeh.sampledata.download(progress=False)'
RUN cd /examples/app/stocks && python download_sample_data.py && cd /

ADD https://raw.githubusercontent.com/bokeh/demo.bokeh.org/main/index.html /index.html

EXPOSE 5006
EXPOSE 80

CMD bokeh serve \
    --allow-websocket-origin="*" \
    --index=/index.html \
    --log-level=${BOKEH_LOG_LEVEL} \
    --num-procs=${NUM_PROCS} \
    /examples/app/crossfilter \
    /examples/app/export_csv \
    /examples/app/gapminder \
    /examples/app/movies \
    /examples/app/selection_histogram.py \
    /examples/app/sliders.py \
    /examples/app/surface3d \
    /examples/app/stocks \
    /examples/app/weather
