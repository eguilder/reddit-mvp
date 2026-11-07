const $ = (id) => document.getElementById(id);

async function loadSettings() {
  const settings = await fetch('/api/settings').then((r) => r.json());
  $('interests').value = settings.interests.join('\n');
  $('avoid').value = settings.avoid.join('\n');
  $('subreddits').value = settings.subreddits.join(', ');
  $('minimum_score').value = settings.minimum_score;
}

async function saveSettings() {
  const payload = {
    interests: $('interests').value.split('\n').map((x) => x.trim()).filter(Boolean),
    avoid: $('avoid').value.split('\n').map((x) => x.trim()).filter(Boolean),
    subreddits: $('subreddits').value.split(',').map((x) => x.trim()).filter(Boolean),
    minimum_score: Number($('minimum_score').value),
    limit: 40,
  };
  await fetch('/api/settings', { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
  $('status').textContent = 'Saved.';
  await loadFeed();
}

function render(posts, mode) {
  $('count').textContent = `${posts.length} posts · ${mode} scoring`;
  $('feed').innerHTML = posts.length ? posts.map((post) => `
    <article class="post card" data-id="${post.id}">
      <div class="post-meta">r/${escapeHtml(post.subreddit)} · ${post.interest_score.toFixed(2)} interest · ${post.score} points</div>
      <h3><a href="${post.url}" target="_blank" rel="noreferrer">${escapeHtml(post.title)}</a></h3>
      <p>${escapeHtml(post.reason)}</p>
      <div class="actions"><button onclick="feedback('${post.id}', 'more')">More like this</button><button onclick="feedback('${post.id}', 'less')">Less like this</button></div>
    </article>`).join('') : '<div class="card muted">No posts matched. Lower the threshold or broaden your interests.</div>';
}

function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }

async function loadFeed() {
  $('feed').innerHTML = '<div class="card muted">Refreshing…</div>';
  const response = await fetch('/api/feed');
  const data = await response.json();
  if (!response.ok) { $('feed').innerHTML = `<div class="card error">${escapeHtml(data.detail || 'Could not load feed')}</div>`; return; }
  render(data.posts, data.mode);
}

async function feedback(postId, label) {
  await fetch('/api/feedback', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({post_id: postId, label}) });
  document.querySelector(`[data-id="${postId}"]`)?.remove();
}

$('save').addEventListener('click', saveSettings);
$('refresh').addEventListener('click', loadFeed);
loadSettings().then(loadFeed).catch((error) => { $('feed').innerHTML = `<div class="card error">${escapeHtml(error.message)}</div>`; });
