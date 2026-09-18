function renderPasswordChange(message='') {
  app.innerHTML=`<main class="page-shell"><section class="card panel"><h2>修改密码</h2><p>${State.user?.must_change_password?'首次登录或重置后需要设置个人密码。':'修改后所有设备需要重新登录。'}</p><p>至少16个字符，最多72个UTF-8字节。建议使用密码管理器生成密码。</p><form id="passwordForm"><label class="label" for="currentPassword">当前密码</label><input class="input" id="currentPassword" type="password" autocomplete="current-password" required><label class="label" for="newPassword">新密码</label><input class="input" id="newPassword" type="password" autocomplete="new-password" minlength="16" required><label class="label" for="confirmPassword">确认新密码</label><input class="input" id="confirmPassword" type="password" autocomplete="new-password" required><p role="alert">${escapeHtml(message)}</p><button class="btn primary" type="submit">修改并重新登录</button></form></section></main>`;
  document.getElementById('passwordForm').onsubmit=async e=>{
    e.preventDefault();
    const current=document.getElementById('currentPassword').value;
    const next=document.getElementById('newPassword').value;
    if(next!==document.getElementById('confirmPassword').value)return renderPasswordChange('两次新密码不一致');
    if(new TextEncoder().encode(next).length>72)return renderPasswordChange('新密码超过72个UTF-8字节');
    const button=e.currentTarget.querySelector('button');button.disabled=true;
    try {await api('/auth/password',{method:'POST',body:JSON.stringify({current_password:current,new_password:next})});saveAuth(null,null);State.user=null;beginNavigation('login');renderLogin('密码已修改，请使用新密码登录。');}
    catch(err){if(err.status===401){State.user=null;beginNavigation('login');renderLogin('会话已失效，请重新登录。');}else renderPasswordChange(err.message);}
  };
}
