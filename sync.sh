while true; do
    rsync -avz --include="leaderboards.py" --exclude="*" -d -e "ssh -i ~/.ssh/tecenet_ql_vpn.pem" /Users/robertoreale/webdev/minqlx-plugins/ ubuntu@42.192.104.108:/home/ubuntu/quakelive-server-standards/minqlx-plugins/standard/ca
    sleep 3
done
