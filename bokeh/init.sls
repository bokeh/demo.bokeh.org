
include: 
  - nginx

git-bokeh:
  git.latest:
    - name: https://github.com/bokeh/bokeh.git
    - target: /home/ec2-user/bokeh

git-bokeh-demos:
  git.latest:
    - name: https://github.com/bokeh/bokeh-demos.git
    - target: /home/ec2-user/bokeh-demos


supervisor-conf:
  file.managed:
    - name: /home/ec2-user/miniconda/envs/supervisor/etc/supervisor/supervisor.conf
    - source: salt://bokeh/templates/supervisor.conf
    - makedirs: true
    - user: root
    - group: root


supervisord-running:
  cmd.run:
    - name: /home/ec2-user/miniconda/envs/supervisor/bin/supervisord -c /home/ec2-user/miniconda/envs/supervisor/etc/supervisor/supervisor.conf
    - unless: |
              test -e /home/ec2-user/miniconda/envs/supervisor/var/run/supervisor.sock &&
              test -e /home/ec2-user/miniconda/envs/supervisor/var/run/supervisord.pid &&
              ps cax | grep supervisord > /dev/null


bokeh-server-conf:
  file.managed:
    - name: /home/ec2-user/miniconda/envs/supervisor/etc/supervisor/conf.d/bokeh-server.conf
    - source: salt://bokeh/templates/bokeh-server.conf
    - template: jinja
    - makedirs: true
    - user: root
    - group: root


bokeh-update-supervisor:
  cmd.wait:
    - name: /home/ec2-user/miniconda/envs/supervisor/bin/supervisorctl -c /home/ec2-user/miniconda/envs/supervisor/etc/supervisor/supervisor.conf update && sleep 2
    - watch:
      - file: bokeh-server-conf

bokeh-server-running:
  cmd.run:
    - name: /home/ec2-user/miniconda/envs/supervisor/bin/supervisorctl -c /home/ec2-user/miniconda/envs/supervisor/etc/supervisor/supervisor.conf start 'bokeh_demos:*'
