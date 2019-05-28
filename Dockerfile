FROM frolvlad/alpine-miniconda3
LABEL org.bokeh.demo.maintainer="Bokeh <bokehplots@gmail.com>"

ENV BK_VERSION=1.2.0
ENV PY_VERSION=3.7
ENV NUM_PROCS=4

RUN apk add --no-cache  git bash

RUN git clone --branch $BK_VERSION https://github.com/bokeh/bokeh.git /bokeh

RUN mkdir -p /examples && cp -r /bokeh/examples/app /examples/ && rm -rf /bokeh

RUN conda config --set auto_update_conda off && conda config --append channels bokeh --append channels bokeh/c/dev
RUN conda install --yes --quiet python=${PY_VERSION} pyyaml jinja2 bokeh=${BK_VERSION} numpy numba scipy sympy nodejs>=8.8 pandas scikit-learn
RUN conda clean -ay

RUN python -c 'import bokeh; bokeh.sampledata.download(progress=False)'
RUN cd /examples/app/stocks && python download_sample_data.py && cd /

ADD https://raw.githubusercontent.com/bokeh/demo.bokeh.org/master/index.html /index.html

EXPOSE 5006
EXPOSE 80

CMD bokeh serve \
    --allow-websocket-origin="*" \
    --index=/index.html \
    --num-procs=${NUM_PROCS} \
    /examples/app/clustering \
    /examples/app/crossfilter \
    /examples/app/dash \
    /examples/app/export_csv \
    /examples/app/fourier_animated.py \
    /examples/app/gapminder \
    /examples/app/image_blur.py \
    /examples/app/movies \
    /examples/app/ohlc \
    /examples/app/population.py \
    /examples/app/selection_histogram.py \
    /examples/app/sliders.py \
    /examples/app/spectrogram \
    /examples/app/surface3d \
    /examples/app/stocks \
    /examples/app/taylor.py \
    /examples/app/weather
