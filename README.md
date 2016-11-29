# demo.bokehplots.com
Hosted Bokeh App Demos

Bash/Salt deploy of Miniconda/Nginx/Bokeh Server

```
./deploy.sh -h    # help
./deploy.sh       # deploy everything with a default of 6 servers
./deploy.sh -s 16 # optionally define number of servers (up to 99) 
./deploy.sh -n SERVER_NAME # optionally define dns name for NGINX/BOKEH
```

## Bokeh Server Logs

/home/ec2-user/log/
