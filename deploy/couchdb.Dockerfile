FROM couchdb:3.4.3
COPY --chown=couchdb:couchdb couchdb.ini /opt/couchdb/etc/local.d/ink2vault.ini
