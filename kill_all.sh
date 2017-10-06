#!/bin/bash
sudo /home/ec2-user/miniconda3/envs/supervisor/bin/supervisorctl -c /home/ec2-user/miniconda3/envs/supervisor/etc/supervisor/supervisord.conf stop all
sudo pkill -f salt
sudo pkill -f supervisor
