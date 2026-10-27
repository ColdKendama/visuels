/**
 * Galeries de visuels : reçoit la sélection « à revoir » d'une galerie
 * (coldkendama.github.io/visuels/<client>/) et l'envoie par courriel au
 * compte qui a déployé le script. Aucune adresse n'est écrite ici ni dans les
 * pages : le destinataire est toujours le propriétaire du déploiement.
 *
 * Déploiement : script.google.com > Nouveau projet > coller ce fichier >
 * Déployer > Nouveau déploiement > Application Web, « Exécuter en tant que :
 * Moi », « Qui a accès : Tout le monde ». L'URL /exec va dans la constante
 * ENVOI de la page.
 */

const SITE = 'https://coldkendama.github.io/visuels/';
const CLIENTS = { floorbox: 'FloorBox' };
const MAX_VISUELS = 200;
const MAX_TEXTE = 3000;
const MAX_ENVOIS_PAR_HEURE = 20;

function doGet() {
  return repondre({ ok: true });
}

function doPost(e) {
  try {
    const d = JSON.parse(e.postData.contents);
    const client = String(d.client || '');
    if (!CLIENTS[client]) throw new Error('client inconnu');
    const visuels = (Array.isArray(d.visuels) ? d.visuels : []).slice(0, MAX_VISUELS).map(nettoyer);
    if (!visuels.length) throw new Error('aucun visuel sélectionné');
    limiter();

    const nom = court(d.nom, 120);
    const commentaire = court(d.commentaire, MAX_TEXTE);
    const marque = CLIENTS[client];
    const n = visuels.length;
    const sujet = `${marque} : ${n} visuel${n > 1 ? 's' : ''} à revoir${nom ? ' (' + nom + ')' : ''}`;

    MailApp.sendEmail({
      to: Session.getEffectiveUser().getEmail(),
      subject: sujet,
      name: `Galerie ${marque}`,
      body: texte(marque, nom, commentaire, visuels),
      htmlBody: html(client, marque, nom, commentaire, visuels),
    });
    return repondre({ ok: true, envoyes: n });
  } catch (err) {
    return repondre({ ok: false, erreur: String((err && err.message) || err) });
  }
}

// Les champs affichés dans le courriel, tronqués ; l'image n'est acceptée que
// si c'est une miniature de la galerie.
function nettoyer(v) {
  const mini = String((v && v.mini) || '');
  return {
    nom: court(v && v.nom, 200),
    pays: { CA: 'Canada', US: 'États-Unis' }[v && v.pays] || '',
    section: court(v && v.section, 80),
    marque: court(v && v.marque, 80),
    langue: court(v && v.langue, 5),
    titre: court(v && v.titre, 200),
    note: court(v && v.note, MAX_TEXTE),
    mini: /^images\/min\/[A-Za-z0-9_-]+\.jpg$/.test(mini) ? mini : '',
  };
}

function court(valeur, max) {
  return String(valeur == null ? '' : valeur).trim().slice(0, max);
}

function limiter() {
  const cache = CacheService.getScriptCache();
  const cle = 'envois-' + Math.floor(Date.now() / 3600000);
  const n = Number(cache.get(cle) || 0);
  if (n >= MAX_ENVOIS_PAR_HEURE) throw new Error('trop d’envois cette heure-ci, réessayez plus tard');
  cache.put(cle, String(n + 1), 3700);
}

function contexte(v) {
  return [v.pays, v.section, v.marque, v.langue].filter(String).join(' · ');
}

function texte(marque, nom, commentaire, visuels) {
  const lignes = [`${visuels.length} visuel(s) ${marque} à revoir${nom ? ', envoyé par ' + nom : ''}.`];
  if (commentaire) lignes.push('', 'Commentaire général :', commentaire);
  visuels.forEach((v, i) => {
    lignes.push('', `${i + 1}. ${contexte(v)}`, `   Annonce : ${v.nom}`, `   Titre : ${v.titre}`,
      `   Note : ${v.note || 'aucune'}`);
  });
  return lignes.join('\n');
}

function html(client, marque, nom, commentaire, visuels) {
  const galerie = SITE + client + '/';
  const lignes = visuels.map((v, i) => `
    <tr>
      <td style="padding:12px 12px 12px 0;vertical-align:top;width:132px">
        ${v.mini ? `<img src="${esc(galerie + v.mini)}" width="120" style="display:block;border-radius:6px;border:1px solid #e2ddd5" alt="">` : ''}
      </td>
      <td style="padding:12px 0;vertical-align:top;font:14px/1.45 Arial,sans-serif;color:#111d1d">
        <div style="font-size:12px;color:#5d6868">${i + 1}. ${esc(contexte(v))}</div>
        <div style="font-weight:bold;margin:2px 0">${esc(v.titre)}</div>
        <div style="font-size:12px;color:#5d6868">Annonce : ${esc(v.nom)}</div>
        <div style="margin-top:8px;padding:8px 10px;background:#f5f2ed;border-radius:6px">
          ${v.note ? esc(v.note).replace(/\n/g, '<br>') : '<i style="color:#5d6868">Aucune note</i>'}
        </div>
      </td>
    </tr>`).join('<tr><td colspan="2" style="border-top:1px solid #e2ddd5"></td></tr>');

  return `
  <div style="font:14px/1.5 Arial,sans-serif;color:#111d1d;max-width:640px">
    <p style="margin:0 0 4px;font-size:18px;font-weight:bold">${visuels.length} visuel${visuels.length > 1 ? 's' : ''} ${esc(marque)} à revoir</p>
    <p style="margin:0 0 12px;color:#5d6868">${nom ? 'Envoyé par ' + esc(nom) + ' depuis' : 'Envoyé depuis'}
      <a href="${esc(galerie)}" style="color:#1c786e">la galerie</a>.</p>
    ${commentaire ? `<p style="margin:0 0 12px;padding:10px 12px;background:#f5f2ed;border-radius:6px"><b>Commentaire général</b><br>${esc(commentaire).replace(/\n/g, '<br>')}</p>` : ''}
    <table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%">${lignes}</table>
  </div>`;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function repondre(objet) {
  return ContentService.createTextOutput(JSON.stringify(objet)).setMimeType(ContentService.MimeType.JSON);
}
