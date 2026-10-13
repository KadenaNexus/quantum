# Quantum-Safe Kadena deployment

Production host: Hetzner server `89.167.14.58`
Hostname: `quantum.kadena.ws`
Web root: `/var/www/quantum.kadena.ws`
Web-root/cron user: `mustafa`

The live site is a plain static page served by Nginx over HTTPS. The updater runs as `mustafa`; do not install it as a root cron job.

## First-time setup

Create the web root and copy the site files from a checked-out, reviewed revision:

```sh
sudo install -d -o mustafa -g mustafa /var/www/quantum.kadena.ws
sudo cp index.html nexus-mark.png nexus-mark-64.png assessment.json status.json update_status.py /var/www/quantum.kadena.ws/
sudo chown mustafa:mustafa /var/www/quantum.kadena.ws/{index.html,nexus-mark.png,nexus-mark-64.png,assessment.json,status.json,update_status.py}
sudo chmod 0755 /var/www/quantum.kadena.ws/update_status.py
```

The Nginx server block should serve the directory as static files. Keep the existing TLS configuration and include:

```nginx
root /var/www/quantum.kadena.ws;
index index.html;
charset utf-8;

location / {
    try_files $uri $uri/ =404;
}

location ~* \.json$ {
    add_header Cache-Control "no-cache";
}
```

After changing Nginx, check and reload it:

```sh
sudo nginx -t && sudo systemctl reload nginx
```

If HTTPS has not yet been configured, issue the certificate after the DNS A record points to the Hetzner host:

```sh
sudo certbot --nginx -d quantum.kadena.ws --redirect
```

## Updater and hourly cron

Run the updater once as `mustafa` after the initial install:

```sh
python3 /var/www/quantum.kadena.ws/update_status.py /var/www/quantum.kadena.ws
```

It should write `status.json` and print the effective progress. Warnings for an unavailable source are non-fatal; the last successful data remains available.

Add this line to `mustafa`'s crontab with `crontab -e`:

```cron
17 * * * * /usr/bin/python3 /var/www/quantum.kadena.ws/update_status.py /var/www/quantum.kadena.ws >> /var/log/quantum-status.log 2>&1
```

If the log file does not exist on a new host, create it once and assign it to `mustafa`:

```sh
sudo touch /var/log/quantum-status.log
sudo chown mustafa:mustafa /var/log/quantum-status.log
```

The updater uses the Saudi Chainweb service API at `http://193.122.85.1:1848` by default. On that node, `serviceApi.interface` must listen on the external interface and its firewall must allow TCP 1848 from `89.167.14.58/32` only. The Oracle security list must have the matching source-restricted ingress rule. Alternatively, set `NODE_URL` in the cron environment to another mainnet service API.

## Updating the static page

After a change has been reviewed and merged, check out the approved revision on the server, then copy the page and mark:

```sh
sudo cp index.html nexus-mark.png nexus-mark-64.png /var/www/quantum.kadena.ws/
sudo chown mustafa:mustafa /var/www/quantum.kadena.ws/index.html /var/www/quantum.kadena.ws/nexus-mark.png /var/www/quantum.kadena.ws/nexus-mark-64.png
```

Nginx serves static files directly, so an HTML-only update needs no service reload. Preserve the existing production `assessment.json` and `status.json` on ordinary page updates; the former stores automatically raised milestone scores, and the latter is refreshed by the hourly job. If `update_status.py` changes, copy it separately and keep the existing cron entry.

Verify the public page over HTTPS, its `Quantum-Safe Kadena | Kadena Nexus` title, the Nexus brand bar and footer links, and the live status line. Check JSON cache headers with:

```sh
curl -sI https://quantum.kadena.ws/status.json | grep -i cache-control
```

Tag the revision used for each production deployment.
