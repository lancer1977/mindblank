using System.Net;
using System.Text;
using System.Text.Json;
using Markdig;
using Markdig.Syntax;
using Microsoft.Data.Sqlite;

public static class Helpers
{
public static int Validate(string path)
{
    using var c = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
    c.Open();
    string Scalar(string sql) { using var m = c.CreateCommand(); m.CommandText = sql; return Convert.ToString(m.ExecuteScalar()) ?? ""; }
    if (Scalar("PRAGMA integrity_check") != "ok") throw new InvalidDataException("integrity");
    if (Scalar("SELECT value FROM meta WHERE key='schema_version'") != "1") throw new InvalidDataException("schema_version");
    if (Scalar("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('notes','notes_fts')") != "2") throw new InvalidDataException("tables");
    Scalar("SELECT slug,title,category,tags,description,body_md,source_path,updated_utc FROM notes LIMIT 1");
    Scalar("SELECT rowid FROM notes_fts WHERE notes_fts MATCH '\"x\"' LIMIT 1");
    return int.Parse(Scalar("SELECT count(*) FROM notes"));
}

public static Dictionary<string, string> Meta(SqliteConnection c)
{
    var d = new Dictionary<string, string>();
    using var m = c.CreateCommand();
    m.CommandText = "SELECT key,value FROM meta";
    using var r = m.ExecuteReader();
    while (r.Read()) d[r.GetString(0)] = r.GetString(1);
    return d;
}

public static List<string> ParseTags(string json)
{
    try { return JsonSerializer.Deserialize<List<string>>(json) ?? new(); } catch { return new(); }
}

public static string H(string? s) => WebUtility.HtmlEncode(s ?? "");

public static string NoteLi(string slug, string title, string? desc) =>
    $"<li><a href=\"/n/{slug.Split('/').Select(Uri.EscapeDataString).Aggregate((x, y) => x + "/" + y)}\">{H(title)}</a>" +
    (string.IsNullOrWhiteSpace(desc) ? "" : $" <span class=\"meta\">{H(desc)}</span>") + "</li>";

public static string SearchBox(string q) =>
    $"<form action=\"/search\" method=\"get\"><input type=\"search\" name=\"q\" value=\"{H(q)}\" placeholder=\"Search runbook\" aria-label=\"Search\"> <button>Search</button></form>";

public static string Slugify(string s)
{
    var sb = new StringBuilder();
    foreach (var ch in s.Trim().ToLowerInvariant())
    {
        if ((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '-' || ch == '/') sb.Append(ch);
        else if (ch == ' ' || ch == '_') sb.Append('-');
    }
    return sb.ToString();
}

public static readonly MarkdownPipeline Pipe = BuildPipe();

static MarkdownPipeline BuildPipe()
{
    var b = new MarkdownPipelineBuilder().UseAdvancedExtensions().DisableHtml();
    // GenericAttributes would let note text inject arbitrary attributes such as onclick.
    b.Extensions.RemoveAll(e => e is Markdig.Extensions.GenericAttributes.GenericAttributesExtension);
    return b.Build();
}

static readonly System.Text.RegularExpressions.Regex SchemeRx = new(@"^([a-zA-Z][a-zA-Z0-9+.\-]*):", System.Text.RegularExpressions.RegexOptions.Compiled);

public static string SafeUrl(string? url)
{
    if (string.IsNullOrEmpty(url)) return url ?? "";
    var norm = new string(WebUtility.HtmlDecode(url).Where(ch => ch > ' ' && ch != '\u007f').ToArray());
    if (norm.StartsWith("//")) return url; // protocol-relative: same policy as http(s)
    var m = SchemeRx.Match(norm);
    if (!m.Success) return url; // relative or fragment
    var scheme = m.Groups[1].Value.ToLowerInvariant();
    return scheme is "http" or "https" or "mailto" ? url : "#";
}
public static readonly System.Text.RegularExpressions.Regex Wiki = new(@"\[\[([^\]\|\r\n]+)(?:\|([^\]\r\n]+))?\]\]", System.Text.RegularExpressions.RegexOptions.Compiled);

public static string RenderMd(string md)
{
    var rewritten = Wiki.Replace(md, m =>
    {
        var target = m.Groups[1].Value.Trim();
        var label = m.Groups[2].Success ? m.Groups[2].Value.Trim() : target;
        return $"[{label}](/n/{Slugify(target)})";
    });
    var doc = Markdown.Parse(rewritten, Pipe);
    foreach (var link in doc.Descendants<Markdig.Syntax.Inlines.LinkInline>())
        link.Url = SafeUrl(link.Url);
    foreach (var auto in doc.Descendants<Markdig.Syntax.Inlines.AutolinkInline>())
        auto.Url = SafeUrl(auto.Url);
    using var sw = new StringWriter();
    var renderer = new Markdig.Renderers.HtmlRenderer(sw);
    Pipe.Setup(renderer);
    renderer.Render(doc);
    return sw.ToString();
}

public static IResult NotFoundPage() =>
    Results.Content(Page("Not found", "<h1>Not found</h1><p><a href=\"/\">Back to index</a></p>"), "text/html; charset=utf-8", Encoding.UTF8, 404);

public static IResult Html(string title, string body) =>
    Results.Content(Page(title, body), "text/html; charset=utf-8", Encoding.UTF8);

public static string Page(string title, string body) => $$$"""
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{{{H(title)}}}</title>
<style>
:root{--bg:#fff;--fg:#1c1c1e;--mut:#6b7280;--ac:#2563eb;--bd:#e5e7eb;--code:#f3f4f6}
@media(prefers-color-scheme:dark){:root{--bg:#111318;--fg:#e5e7eb;--mut:#9ca3af;--ac:#7aa2ff;--bd:#2a2f3a;--code:#1c212b}}
body{margin:0 auto;max-width:48rem;padding:1rem;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif}
a{color:var(--ac)}h1,h2{line-height:1.2}h2{border-bottom:1px solid var(--bd);padding-bottom:.2rem;text-transform:capitalize}
.meta,.desc{color:var(--mut);font-size:.9rem}.tag{border:1px solid var(--bd);border-radius:1rem;padding:0 .6rem;font-size:.85rem;text-decoration:none}
pre,code{background:var(--code);border-radius:4px}code{padding:.1rem .3rem}pre{padding:.75rem;overflow:auto}pre code{padding:0}
table{border-collapse:collapse}td,th{border:1px solid var(--bd);padding:.3rem .6rem}
input[type=search]{padding:.4rem;width:60%;max-width:20rem;background:var(--bg);color:var(--fg);border:1px solid var(--bd);border-radius:4px}
button{padding:.4rem .8rem}ul{padding-left:1.2rem}img{max-width:100%}
</style></head><body><header><a href="/">Runbook</a></header><main>{{{body}}}</main></body></html>
""";
}
