FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY src/Runbook/Runbook.csproj src/Runbook/
RUN dotnet restore src/Runbook/Runbook.csproj
COPY src/Runbook/ src/Runbook/
RUN dotnet publish src/Runbook/Runbook.csproj -c Release --no-restore -o /out /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS runtime
WORKDIR /app
COPY --from=build /out .
ENV ASPNETCORE_URLS=http://+:8080 \
    RUNBOOK_DB_PATH=/data/runbook.db \
    RUNBOOK_IMPORT_KEY_FILE=/run/secrets/runbook_import_key
RUN mkdir -p /data && chown app:app /data
VOLUME /data
USER app
EXPOSE 8080
ENTRYPOINT ["dotnet", "Runbook.dll"]
