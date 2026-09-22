"""Owner-opened local credential form for one new private fixed-tunnel profile.

Saving performs no network request, account operation, service start or Codex
configuration change. Existing profiles are never replaced by this form.
"""
import argparse
import hashlib
from pathlib import Path
import re
from urllib.request import getproxies

from operator_core.web_browser_driver import private_directory
from operator_core.web_mcp_transport import require
from operator_core.web_openai_tunnel import TUNNEL_ID, publish_new, validate_proxy


def save_profile(profile, executable, tunnel_id, key, proxy=None):
    require(isinstance(tunnel_id, str) and TUNNEL_ID.fullmatch(tunnel_id), 'web_fixed_tunnel_id_invalid')
    require(isinstance(key, str) and re.fullmatch(r'sk-[A-Za-z0-9_-]{16,4090}', key),
        'web_fixed_tunnel_key_invalid')
    require(executable.is_absolute() and executable.is_file() and not executable.is_symlink(),
        'web_tunnel_executable_required')
    proxy = validate_proxy(proxy)
    private_directory(profile)
    key_file = profile / 'runtime.key'
    with key_file.open('xb') as stream:
        stream.write(key.encode('ascii'))
    settings = {'mode': 'openai_tunnel_v1', 'tunnel_client': str(executable),
        'tunnel_client_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
        'tunnel_id': tunnel_id, 'api_key_file': str(key_file), 'binding_file': str(profile / 'connector.json'),
        **({'control_plane_proxy': proxy} if proxy else {})}
    publish_new(profile / 'mcp-settings.json', settings)
    publish_new(profile / 'setup-result.json', {'version': 1, 'state': 'saved',
        'key_configured': True, 'expires_at': None, 'service_started': False})
    return settings


def show_form(profile, executable, tunnel_id=None):
    import tkinter as tk
    from tkinter import ttk, messagebox

    root = tk.Tk()
    root.title('Operator · 保存固定连接')
    root.geometry('630x390')
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='固定连接，只需配置一次', font=('Microsoft YaHei UI', 15)).pack(anchor='w')
    ttk.Label(frame, text='密钥仅保存到本机私有目录，不进入聊天记录。\n保存后由 Operator 检查连接，再完成一次插件授权。',
        padding=(0, 10)).pack(anchor='w')
    values = {}
    for name, label, masked in [('tunnel_id', 'Tunnel ID', False), ('key', 'Runtime API key', True),
            ('proxy', '连接代理（可留空；不修改系统设置）', False)]:
        ttk.Label(frame, text=label).pack(anchor='w', pady=(7, 3))
        values[name] = tk.StringVar(value=tunnel_id if name == 'tunnel_id' and tunnel_id else '')
        ttk.Entry(frame, textvariable=values[name], show='●' if masked else '', width=80).pack(fill='x')
    try:
        proxy = getproxies().get('https')
        if proxy:
            values['proxy'].set(validate_proxy(proxy))
    except (ValueError, TypeError):
        pass

    def save():
        try:
            save_profile(profile, executable, values['tunnel_id'].get().strip(),
                values['key'].get().strip(), values['proxy'].get().strip() or None)
        except Exception:
            # Never include a credential, exception body or clipboard data.
            messagebox.showerror('尚未保存', '请核对 Tunnel ID、密钥和代理格式。已有配置不会被覆盖。')
            return
        values['key'].set('')
        messagebox.showinfo('已保存', '固定连接信息已保存到本机。回到 Codex 告诉我“已保存”即可。')
        root.destroy()

    ttk.Button(frame, text='保存到本机', command=save).pack(anchor='e', pady=18)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--tunnel-client', type=Path, required=True)
    parser.add_argument('--tunnel-id', help='Prefill the connection ID already verified in the setup page.')
    args = parser.parse_args()
    if not args.profile.is_absolute() or args.profile.exists() or args.profile.is_symlink():
        raise SystemExit('web_private_directory_must_be_new')
    if args.tunnel_id is not None and not TUNNEL_ID.fullmatch(args.tunnel_id):
        raise SystemExit('web_fixed_tunnel_id_invalid')
    show_form(args.profile, args.tunnel_client, args.tunnel_id)


if __name__ == '__main__':
    main()
