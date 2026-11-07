using System.Net;
using System.Net.Http.Headers;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Data.Sqlite;
using Xunit;

namespace Runbook.Tests;

public sealed class Env : IDisposable
{
    public string Dir = Path.Combine(Path.GetTempPath(), "runbook-test-" + Guid.NewGuid().ToString("N"));
    public string Db => Path.Combine(Dir, "data", "runbook.db");
    public string KeyFile => Path.Combine(Dir, "key");
    public WebApplicationFactory<Program> Factory;

    public Env(string? key = "sample-key", long? maxImport = null, bool withDb = false)
    {
        Directory.CreateDirectory(Path.Combine(Dir, "data"));
        if (key != null) File.WriteAllText(KeyFile, key + "\n");
        if (withDb) Sample.Build(Db);
        Factory = new WebApplicationFactory<Program>().WithWebHostBuilder(b =>
        {
            b.UseSetting("RUNBOOK_DB_PATH", Db);
            b.UseSetting("RUNBOOK_IMPORT_KEY_FILE", KeyFile);
            if (maxImport != null) b.UseSetting("RUNBOOK_MAX_IMPORT_BYTES", maxImport.ToString());
        });
    }
    public HttpClient Client() => Factory.CreateClient();
    public void Dispose() { Factory.Dispose(); try { Directory.Delete(Dir, true); } catch { } }
}

public static class Sample
{
    public static void Build(string path, string schemaVersion = "1")
    {
        if (File.Exists(path)) File.Delete(path);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        using (var c = new SqliteConnection($"Data Source={path};Pooling=False"))
        {
            c.Open();
            Exec(c, "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)");
            Exec(c, """
                CREATE TABLE notes(
                  slug TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
                  tags TEXT NOT NULL DEFAULT '[]', description TEXT, body_md TEXT NOT NULL,
                  source_path TEXT NOT NULL, updated_utc TEXT NOT NULL)
                """);
            Exec(c, "CREATE VIRTUAL TABLE notes_fts USING fts5(title, description, body_md, content='notes', content_rowid='rowid')");
            Exec(c, $"INSERT INTO meta VALUES('schema_version','{schemaVersion}'),('generated_utc','2026-01-02T03:04:05Z'),('note_count','3')");
            Note(c, "demo/widget-setup", "Widget Setup", "demo", "[\"alpha\",\"beta\"]", "How to set up the sample widget",
                "# Widget Setup\n\nRun the **sample** command. See [[Gadget Notes|the gadget]] and [[Other Page]].\n\n<script>alert(1)</script>\n");
            Note(c, "demo/gadget-notes", "Gadget Notes", "demo", "[\"beta\"]", "Gadget <b>tips</b>", "Gadgets are invented.\n");
            Note(c, "plain-note", "Plain Note", "notes", "[]", null, "Nothing special here.\n");
            Exec(c, "INSERT INTO notes_fts(notes_fts) VALUES('rebuild')");
        }
    }
    static void Exec(SqliteConnection c, string sql) { using var m = c.CreateCommand(); m.CommandText = sql; m.ExecuteNonQuery(); }
    static void Note(SqliteConnection c, string slug, string title, string cat, string tags, string? desc, string body)
    {
        using var m = c.CreateCommand();
        m.CommandText = "INSERT INTO notes VALUES($s,$t,$c,$g,$d,$b,'x.md','2026-01-01T00:00:00Z')";
        m.Parameters.AddWithValue("$s", slug); m.Parameters.AddWithValue("$t", title); m.Parameters.AddWithValue("$c", cat);
        m.Parameters.AddWithValue("$g", tags); m.Parameters.AddWithValue("$d", (object?)desc ?? DBNull.Value); m.Parameters.AddWithValue("$b", body);
        m.ExecuteNonQuery();
    }
    public static byte[] Bytes(string schemaVersion = "1")
    {
        var p = Path.Combine(Path.GetTempPath(), "runbook-sample-" + Guid.NewGuid().ToString("N") + ".db");
        Build(p, schemaVersion);
        var b = File.ReadAllBytes(p); File.Delete(p); return b;
    }
}

public class ViewTests
{
    [Fact]
    public async Task Healthz_ok_without_db()
    {
        using var e = new Env();
        var r = await e.Client().GetAsync("/healthz");
        Assert.Equal(HttpStatusCode.OK, r.StatusCode);
        Assert.Equal("ok", await r.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task Index_without_db_shows_empty_state()
    {
        using var e = new Env();
        var r = await e.Client().GetAsync("/");
        Assert.Equal(HttpStatusCode.OK, r.StatusCode);
        Assert.Contains("No runbook has been imported yet", await r.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task Index_with_db_groups_by_category()
    {
        using var e = new Env(withDb: true);
        var h = await e.Client().GetStringAsync("/");
        Assert.Contains("<h2>demo</h2>", h);
        Assert.Contains("<h2>notes</h2>", h);
        Assert.Contains("Widget Setup", h);
        Assert.Contains("3 notes", h);
        Assert.Contains("2026-01-02T03:04:05Z", h);
        Assert.Contains("Gadget &lt;b&gt;tips&lt;/b&gt;", h);
        Assert.DoesNotContain("<b>tips</b>", h);
    }

    [Fact]
    public async Task Note_renders_markdown_and_tags()
    {
        using var e = new Env(withDb: true);
        var h = await e.Client().GetStringAsync("/n/demo/widget-setup");
        Assert.Contains("<h1>Widget Setup</h1>", h);
        Assert.Contains("<strong>sample</strong>", h);
        Assert.Contains("href=\"/tags/alpha\"", h);
    }

    [Fact]
    public async Task Missing_note_is_404()
    {
        using var e = new Env(withDb: true);
        Assert.Equal(HttpStatusCode.NotFound, (await e.Client().GetAsync("/n/nope/missing")).StatusCode);
    }

    [Fact]
    public async Task Missing_note_without_db_is_404()
    {
        using var e = new Env();
        Assert.Equal(HttpStatusCode.NotFound, (await e.Client().GetAsync("/n/anything")).StatusCode);
    }

    [Fact]
    public async Task Raw_script_is_not_rendered_as_tag()
    {
        using var e = new Env(withDb: true);
        var h = await e.Client().GetStringAsync("/n/demo/widget-setup");
        Assert.DoesNotContain("<script>alert(1)</script>", h);
        Assert.Contains("&lt;script&gt;", h);
    }

    [Fact]
    public async Task Wikilinks_are_rewritten()
    {
        using var e = new Env(withDb: true);
        var h = await e.Client().GetStringAsync("/n/demo/widget-setup");
        Assert.Contains("<a href=\"/n/gadget-notes\">the gadget</a>", h);
        Assert.Contains("<a href=\"/n/other-page\">Other Page</a>", h);
        Assert.DoesNotContain("[[", h);
    }

    [Fact]
    public async Task Search_finds_notes()
    {
        using var e = new Env(withDb: true);
        var h = await e.Client().GetStringAsync("/search?q=widget");
        Assert.Contains("Widget Setup", h);
        Assert.DoesNotContain("Plain Note", h);
    }

    [Theory]
    [InlineData("\"")]
    [InlineData("\"unbalanced")]
    [InlineData("foo AND OR NOT")]
    [InlineData("a* NEAR(b c) -d ^e")]
    [InlineData("title:x OR (")]
    [InlineData("<script>alert(1)</script>")]
    public async Task Search_with_fts_syntax_does_not_500(string q)
    {
        using var e = new Env(withDb: true);
        var r = await e.Client().GetAsync("/search?q=" + Uri.EscapeDataString(q));
        Assert.Equal(HttpStatusCode.OK, r.StatusCode);
        Assert.DoesNotContain("<script>alert(1)</script>", await r.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task Search_without_query_or_db_is_ok()
    {
        using var e = new Env();
        Assert.Equal(HttpStatusCode.OK, (await e.Client().GetAsync("/search")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await e.Client().GetAsync("/search?q=x")).StatusCode);
    }

    [Fact]
    public async Task Tag_page_lists_matching_notes()
    {
        using var e = new Env(withDb: true);
        var h = await e.Client().GetStringAsync("/tags/beta");
        Assert.Contains("Widget Setup", h);
        Assert.Contains("Gadget Notes", h);
        Assert.DoesNotContain("Plain Note", h);
    }
}

public class ImportTests
{
    static HttpRequestMessage Put(byte[] body, string? key)
    {
        var m = new HttpRequestMessage(HttpMethod.Put, "/api/import") { Content = new ByteArrayContent(body) };
        m.Content.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        if (key != null) m.Headers.Add("X-Runbook-Import-Key", key);
        return m;
    }

    [Fact]
    public async Task Missing_key_file_is_503()
    {
        using var e = new Env(key: null);
        var r = await e.Client().SendAsync(Put(Sample.Bytes(), "anything"));
        Assert.Equal(HttpStatusCode.ServiceUnavailable, r.StatusCode);
    }

    [Fact]
    public async Task Empty_key_file_is_503()
    {
        using var e = new Env(key: "   ");
        var r = await e.Client().SendAsync(Put(Sample.Bytes(), ""));
        Assert.Equal(HttpStatusCode.ServiceUnavailable, r.StatusCode);
    }

    [Fact]
    public async Task Wrong_or_absent_key_is_401_and_never_echoed()
    {
        using var e = new Env();
        var r = await e.Client().SendAsync(Put(Sample.Bytes(), "wrong-key"));
        Assert.Equal(HttpStatusCode.Unauthorized, r.StatusCode);
        Assert.DoesNotContain("sample-key", await r.Content.ReadAsStringAsync());
        Assert.Equal(HttpStatusCode.Unauthorized, (await e.Client().SendAsync(Put(Sample.Bytes(), null))).StatusCode);
        Assert.False(File.Exists(e.Db));
    }

    [Fact]
    public async Task Garbage_body_is_400()
    {
        using var e = new Env();
        var r = await e.Client().SendAsync(Put("this is not sqlite"u8.ToArray(), "sample-key"));
        Assert.Equal(HttpStatusCode.BadRequest, r.StatusCode);
        Assert.False(File.Exists(e.Db));
    }

    [Fact]
    public async Task Wrong_schema_version_is_400()
    {
        using var e = new Env();
        var r = await e.Client().SendAsync(Put(Sample.Bytes("2"), "sample-key"));
        Assert.Equal(HttpStatusCode.BadRequest, r.StatusCode);
        Assert.False(File.Exists(e.Db));
    }

    [Fact]
    public async Task Valid_db_is_200_and_content_visible_and_no_temp_left()
    {
        using var e = new Env();
        var c = e.Client();
        Assert.Contains("No runbook", await c.GetStringAsync("/"));
        var r = await c.SendAsync(Put(Sample.Bytes(), "sample-key"));
        Assert.Equal(HttpStatusCode.OK, r.StatusCode);
        Assert.Contains("\"notes\":3", await r.Content.ReadAsStringAsync());
        Assert.Contains("Widget Setup", await c.GetStringAsync("/"));
        Assert.Contains("<h1>Widget Setup</h1>", await c.GetStringAsync("/n/demo/widget-setup"));
        Assert.Single(Directory.GetFiles(Path.GetDirectoryName(e.Db)!));
    }

    [Fact]
    public async Task Oversized_body_is_413()
    {
        using var e = new Env(maxImport: 1024);
        var r = await e.Client().SendAsync(Put(new byte[4096], "sample-key"));
        Assert.Equal(HttpStatusCode.RequestEntityTooLarge, r.StatusCode);
        Assert.False(File.Exists(e.Db));
    }
}
