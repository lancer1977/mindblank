using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Markdig;
using Microsoft.Data.Sqlite;
using static Helpers;

var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

app.Use(async (ctx, next) =>
{
    var h = ctx.Response.Headers;
    h["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data: https:; form-action 'self'; base-uri 'none'; frame-ancestors 'none'";
    h["X-Content-Type-Options"] = "nosniff";
    h["Referrer-Policy"] = "no-referrer";
    await next();
});

var cfg = app.Configuration;
string DbPath() => cfg["RUNBOOK_DB_PATH"] is { Length: > 0 } p ? p : "/data/runbook.db";
string KeyFile() => cfg["RUNBOOK_IMPORT_KEY_FILE"] is { Length: > 0 } p ? p : "/run/secrets/runbook_import_key";
long MaxImport() => long.TryParse(cfg["RUNBOOK_MAX_IMPORT_BYTES"], out var n) && n > 0 ? n : 50L * 1024 * 1024;

// Remove stale partial uploads left by a crash mid-import.
try
{
    var startDir = Path.GetDirectoryName(Path.GetFullPath(DbPath()));
    if (startDir != null && Directory.Exists(startDir))
        foreach (var f in Directory.EnumerateFiles(startDir, ".import-*.tmp"))
            try { File.Delete(f); } catch { }
}
catch { }

app.MapGet("/healthz", () => Results.Text("ok"));

app.MapGet("/", () =>
{
    if (!File.Exists(DbPath()))
        return Html("Runbook", "<p class=\"empty\">No runbook has been imported yet.</p>");
    using var c = Open();
    var meta = Meta(c);
    var sb = new StringBuilder();
    sb.Append(SearchBox(""));
    sb.Append($"<p class=\"meta\">{H(meta.GetValueOrDefault("note_count", "0"))} notes &middot; generated {H(meta.GetValueOrDefault("generated_utc", "?"))}</p>");
    using var cmd = c.CreateCommand();
    cmd.CommandText = "SELECT slug,title,category,description FROM notes ORDER BY category, title";
    using var r = cmd.ExecuteReader();
    string? cat = null;
    while (r.Read())
    {
        var rc = r.GetString(2);
        if (rc != cat)
        {
            if (cat != null) sb.Append("</ul>");
            sb.Append($"<h2>{H(rc)}</h2><ul>");
            cat = rc;
        }
        sb.Append(NoteLi(r.GetString(0), r.GetString(1), r.IsDBNull(3) ? null : r.GetString(3)));
    }
    if (cat != null) sb.Append("</ul>");
    return Html("Runbook", sb.ToString());
});

app.MapGet("/n/{**slug}", (string slug) =>
{
    if (!File.Exists(DbPath())) return NotFoundPage();
    using var c = Open();
    using var cmd = c.CreateCommand();
    cmd.CommandText = "SELECT title,category,tags,description,body_md,updated_utc FROM notes WHERE slug=$s";
    cmd.Parameters.AddWithValue("$s", slug);
    using var r = cmd.ExecuteReader();
    if (!r.Read()) return NotFoundPage();
    var sb = new StringBuilder();
    sb.Append($"<p class=\"meta\"><a href=\"/\">Index</a> &rsaquo; {H(r.GetString(1))}</p>");
    sb.Append($"<h1>{H(r.GetString(0))}</h1>");
    if (!r.IsDBNull(3)) sb.Append($"<p class=\"desc\">{H(r.GetString(3))}</p>");
    sb.Append("<p class=\"tags\">");
    foreach (var t in ParseTags(r.GetString(2)))
        sb.Append($"<a class=\"tag\" href=\"/tags/{Uri.EscapeDataString(t)}\">{H(t)}</a> ");
    sb.Append($"</p><article>{RenderMd(r.GetString(4))}</article>");
    sb.Append($"<p class=\"meta\">Updated {H(r.GetString(5))}</p>");
    return Html(r.GetString(0), sb.ToString());
});

app.MapGet("/search", (string? q) =>
{
    q = (q ?? "").Trim();
    var sb = new StringBuilder(SearchBox(q));
    if (q.Length > 0 && File.Exists(DbPath()))
    {
        using var c = Open();
        using var cmd = c.CreateCommand();
        cmd.CommandText = "SELECT n.slug,n.title,n.description FROM notes_fts f JOIN notes n ON n.rowid=f.rowid WHERE notes_fts MATCH $q ORDER BY rank LIMIT 100";
        cmd.Parameters.AddWithValue("$q", "\"" + q.Replace("\"", "\"\"") + "\"");
        var n = 0;
        var items = new StringBuilder();
        try
        {
            using var r = cmd.ExecuteReader();
            while (r.Read()) { n++; items.Append(NoteLi(r.GetString(0), r.GetString(1), r.IsDBNull(2) ? null : r.GetString(2))); }
        }
        catch (SqliteException) { n = 0; items.Clear(); }
        sb.Append($"<p class=\"meta\">{n} result(s) for &ldquo;{H(q)}&rdquo;</p><ul>{items}</ul>");
    }
    else if (q.Length > 0) sb.Append("<p class=\"empty\">No runbook has been imported yet.</p>");
    return Html("Search", sb.ToString());
});

app.MapGet("/tags/{tag}", (string tag) =>
{
    var sb = new StringBuilder($"<h1>Tag: {H(tag)}</h1><ul>");
    if (File.Exists(DbPath()))
    {
        using var c = Open();
        using var cmd = c.CreateCommand();
        cmd.CommandText = "SELECT slug,title,description,tags FROM notes ORDER BY title";
        using var r = cmd.ExecuteReader();
        while (r.Read())
            if (ParseTags(r.GetString(3)).Contains(tag))
                sb.Append(NoteLi(r.GetString(0), r.GetString(1), r.IsDBNull(2) ? null : r.GetString(2)));
    }
    sb.Append("</ul>");
    return Html("Tag " + tag, sb.ToString());
});

app.MapPut("/api/import", async (HttpRequest req) =>
{
    string key;
    try { key = File.Exists(KeyFile()) ? File.ReadAllText(KeyFile()).Trim() : ""; }
    catch { key = ""; }
    if (key.Length == 0) return Results.StatusCode(503);

    var given = req.Headers["X-Runbook-Import-Key"].ToString();
    var a = SHA256.HashData(Encoding.UTF8.GetBytes(given));
    var b = SHA256.HashData(Encoding.UTF8.GetBytes(key));
    if (!CryptographicOperations.FixedTimeEquals(a, b)) return Results.StatusCode(401);

    var max = MaxImport();
    if (req.ContentLength > max) return Results.StatusCode(413);
    var sizeFeature = req.HttpContext.Features.Get<Microsoft.AspNetCore.Http.Features.IHttpMaxRequestBodySizeFeature>();
    if (sizeFeature is { IsReadOnly: false }) sizeFeature.MaxRequestBodySize = max;

    var dbPath = Path.GetFullPath(DbPath());
    var dir = Path.GetDirectoryName(dbPath)!;
    Directory.CreateDirectory(dir);
    var tmp = Path.Combine(dir, $".import-{Guid.NewGuid():N}.tmp");
    try
    {
        long total = 0;
        await using (var fs = new FileStream(tmp, FileMode.CreateNew, FileAccess.Write))
        {
            var buf = new byte[81920];
            int n;
            while ((n = await req.Body.ReadAsync(buf)) > 0)
            {
                total += n;
                if (total > max) return Results.StatusCode(413);
                await fs.WriteAsync(buf.AsMemory(0, n));
            }
        }
        if (total == 0) return Results.BadRequest(new { error = "empty body" });
        int count;
        try { count = Validate(tmp); }
        catch (Exception) { return Results.BadRequest(new { error = "invalid runbook database" }); }
        File.Move(tmp, dbPath, overwrite: true);
        return Results.Json(new { notes = count });
    }
    catch (Microsoft.AspNetCore.Http.BadHttpRequestException ex) when (ex.StatusCode == 413) { return Results.StatusCode(413); }
    finally { try { File.Delete(tmp); } catch { } }
});

app.Run();

// ---------- helpers ----------
SqliteConnection Open()
{
    var c = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = DbPath(), Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
    c.Open();
    return c;
}

public partial class Program { }
