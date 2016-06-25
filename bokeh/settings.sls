
{%- set SUPERVISORENV = '/home/ec2-user/miniconda/envs/supervisor' -%}
{%- set SUPERVISORD = SUPERVISORENV ~ '/bin/supervisord' -%}
{%- set SUPERVISORCTL = SUPERVISORENV ~ '/bin/supervisorctl' -%}
{%- set SUPERVISOR_CONF = SUPERVISORENV ~ "/etc/supervisor/supervisord.conf" -%}
{%- set SUPERVISOR_SOCK = SUPERVISORENV ~ "/var/run/supervisor.sock" -%}
{%- set SUPERVISOR_PID = SUPERVISORENV ~ "/var/run/supervisor.pid" -%}
{%- set SUPERVISOR_BOKEH = SUPERVISORENV ~ "/etc/supervisor/conf.d/bokeh-server.conf" -%}



{% set BOKEH_DEMOS_LIST = ['bokeh/examples/app/movies',
                           'bokeh/examples/app/weather',
                           'bokeh/examples/app/crossfilter',
                           'bokeh/examples/app/gapminder',
                           'bokeh/examples/app/surface3d',
                           'bokeh/examples/app/selection_histogram.py',
                           'bokeh/examples/app/sliders.py',
                           'bokeh/examples/app/stocks',
                           'bokeh/examples/app/export_csv'
                           ] %}
