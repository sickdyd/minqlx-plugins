while true; do
    rsync -avz --include="*.py" --exclude="*" -d -e "ssh -i ~/.ssh/tecenet_ql_vpn.pem" /Users/robertoreale/webdev/minqlx-plugins/ qlserver@42.192.104.108:/home/qlserver/serverfiles/minqlx-plugins/
    sleep 3
done
