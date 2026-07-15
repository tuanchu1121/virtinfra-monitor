# Ansible deployment

## Agent fleet

The Ansible control server can be completely separate from the Monitor.

Example inventory:

```ini
[agents]
192.0.2.10 ansible_port=22
192.0.2.11 ansible_port=1812

[agents:vars]
ansible_user=root
ansible_python_interpreter=/usr/bin/python3
```

Test SSH:

```bash
ansible all -i ansible/test.txt -m ping --forks 20
```

Deploy/update Agent:

```bash
read -rsp 'Nhập VirtInfra Agent token: ' BW_TOKEN
echo

bash ansible/deploy-agent.sh \
-i ansible/test.txt \
--api 'https://monitor.example.com/push' \
--token "$BW_TOKEN" \
--forks 20 \
--serial 10

unset BW_TOKEN
```

Deploy one group or node:

```bash
... --limit 'EPYC_SG'
```

When `ansible_user=root`, the playbook does not invoke `sudo`. For a non-root SSH user, install/configure sudo and privilege escalation.

## Monitor through Ansible

Create an inventory group `[monitors]`, copy `ansible/monitor-vars.example.yml`, encrypt the real vars with Ansible Vault, then:

```bash
ansible-playbook \
-i ansible/monitor-inventory.ini \
ansible/deploy-monitor.yml \
-e @ansible/monitor-vars.yml \
--ask-vault-pass
```
