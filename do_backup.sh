#!/bin/bash

ssh -q -o BatchMode=yes  -o StrictHostKeyChecking=no -o ConnectTimeout=5 $1 'exit 0'
if [ $? == 0 ];then
   echo "Online check succeeded."
else
   echo "Backup target is offline."
fi
