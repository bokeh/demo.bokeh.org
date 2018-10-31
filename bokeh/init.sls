{%- from 'bokeh/settings.sls' import SUPERVISORENV, SUPERVISORD, SUPERVISORCTL, SUPERVISOR_CONF, 
                              SUPERVISOR_SOCK, SUPERVISOR_PID, SUPERVISOR_BOKEH with context -%}

include: 
  - nginx

git-bokeh:
  git.latest:
    - name: https://github.com/bokeh/bokeh.git
    - rev: 1.0.0
    - target: /home/ec2-user/bokeh

supervisor-conf:
  file.managed:
    - name: {{ SUPERVISOR_CONF }} 
    - source: salt://bokeh/templates/supervisor.conf
    - makedirs: true
    - user: root
    - group: root


supervisord-running:
  cmd.run:
    - name: {{ SUPERVISORD }} -c {{ SUPERVISOR_CONF }} 
    - unless: |
              test -e {{ SUPERVISOR_SOCK }}
              ps cax | grep supervisord > /dev/null


bokeh-server-conf:
  file.managed:
    - name: {{ SUPERVISOR_BOKEH }} 
    - source: salt://bokeh/templates/bokeh-server.conf
    - template: jinja
    - makedirs: true
    - user: root
    - group: root


bokeh-update-supervisor:
  cmd.wait:
    - name: {{ SUPERVISORCTL }} -c {{ SUPERVISOR_CONF }} update && sleep 2
    - watch:
      - file: bokeh-server-conf

bokeh-server-running:
  cmd.run:
    - name: {{ SUPERVISORCTL }} -c {{ SUPERVISOR_CONF }} start 'bokeh_demos:*'
