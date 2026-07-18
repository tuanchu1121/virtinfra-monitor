server {
    listen 80;
    listen [::]:80;
    server_name __DOMAIN__;
    client_max_body_size 32m;

    location / {
        proxy_pass http://127.0.0.1:__PORT__;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_connect_timeout 5s;
        proxy_next_upstream error timeout http_502 http_503 http_504;
        proxy_next_upstream_tries 2;
        proxy_buffering on;
        proxy_buffers 16 32k;
        proxy_buffer_size 64k;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }
}
