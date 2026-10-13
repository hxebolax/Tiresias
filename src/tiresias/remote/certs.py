"""Certificado autofirmado del servidor local (conexión directa).

El certificado y su clave privada se generan la primera vez con la librería
``cryptography`` y se guardan en ``data/config/remote`` (``servidor.pem``,
``servidor.key`` y ``servidor.huella``). Se renuevan solos cuando les queda
poco tiempo de validez. Quien se conecte a este equipo verá la huella
SHA-256 y decidirá si confía en ella.
"""

from __future__ import annotations

import datetime
import os
import ssl
import tempfile

from ..log import getLogger

log = getLogger("remote")

CERT_DAYS = 365
RENEW_DAYS = 30


class CertificateManager:
	def __init__(self, folder: str) -> None:
		self.folder = folder
		self.certPath = os.path.join(folder, "servidor.pem")
		self.keyPath = os.path.join(folder, "servidor.key")
		self.fingerprintPath = os.path.join(folder, "servidor.huella")
		self._cert: bytes | None = None
		self._key: bytes | None = None
		self.fingerprint: str | None = None

	def ensureValid(self) -> str:
		"""Carga el certificado guardado o genera uno nuevo. Devuelve la huella."""
		if all(os.path.isfile(p) for p in (self.certPath, self.keyPath)):
			try:
				self._load()
				return self.fingerprint  # type: ignore[return-value]
			except Exception as e:
				log.info("Se regenera el certificado del servidor local: %s", e)
		self._generate()
		return self.fingerprint  # type: ignore[return-value]

	def _load(self) -> None:
		from cryptography import x509
		from cryptography.hazmat.primitives import hashes, serialization

		with open(self.certPath, "rb") as f:
			certData = f.read()
		with open(self.keyPath, "rb") as f:
			keyData = f.read()
		cert = x509.load_pem_x509_certificate(certData)
		now = datetime.datetime.now(datetime.timezone.utc)
		if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
			raise ValueError("certificado caducado")
		if (cert.not_valid_after_utc - now).days <= RENEW_DAYS:
			raise ValueError("certificado a punto de caducar")
		key = serialization.load_pem_private_key(keyData, password=None)
		if key.public_key().public_numbers() != cert.public_key().public_numbers():  # type: ignore[union-attr]
			raise ValueError("la clave no corresponde al certificado")
		self._cert = certData
		self._key = keyData
		self.fingerprint = cert.fingerprint(hashes.SHA256()).hex().lower()

	def _generate(self) -> None:
		from cryptography import x509
		from cryptography.hazmat.primitives import hashes, serialization
		from cryptography.hazmat.primitives.asymmetric import rsa
		from cryptography.x509.oid import NameOID

		key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
		name = x509.Name(
			[
				x509.NameAttribute(NameOID.COMMON_NAME, "Tiresias - acceso remoto"),
				x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Tiresias"),
			]
		)
		now = datetime.datetime.now(datetime.timezone.utc)
		cert = (
			x509.CertificateBuilder()
			.subject_name(name)
			.issuer_name(name)
			.public_key(key.public_key())
			.serial_number(x509.random_serial_number())
			.not_valid_before(now - datetime.timedelta(minutes=5))
			.not_valid_after(now + datetime.timedelta(days=CERT_DAYS))
			.add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
			.add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
			.sign(key, hashes.SHA256())
		)
		self._key = key.private_bytes(
			encoding=serialization.Encoding.PEM,
			format=serialization.PrivateFormat.PKCS8,
			encryption_algorithm=serialization.NoEncryption(),
		)
		self._cert = cert.public_bytes(serialization.Encoding.PEM)
		self.fingerprint = cert.fingerprint(hashes.SHA256()).hex().lower()
		try:
			os.makedirs(self.folder, exist_ok=True)
			for path, data in ((self.keyPath, self._key), (self.certPath, self._cert), (self.fingerprintPath, self.fingerprint.encode("ascii"))):
				tmp = path + ".tmp"
				with open(tmp, "wb") as f:
					f.write(data)
				os.replace(tmp, path)
		except OSError:
			log.warning("No se pudo guardar el certificado del servidor local", exc_info=True)
		log.info("Certificado del servidor local generado (huella %s)", self.fingerprint)

	def serverContext(self) -> ssl.SSLContext:
		if self._cert is None or self._key is None:
			self.ensureValid()
		ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
		ctx.minimum_version = ssl.TLSVersion.TLSv1_2
		if os.path.isfile(self.certPath) and os.path.isfile(self.keyPath):
			try:
				ctx.load_cert_chain(self.certPath, self.keyPath)
				return ctx
			except (OSError, ssl.SSLError):
				log.debug("No se pudo cargar el certificado desde disco", exc_info=True)
		# Sin acceso a disco: archivo temporal (en data\temp) que se borra en seguida.
		from .. import paths

		tmpDir = paths.tempDir()
		try:
			os.makedirs(tmpDir, exist_ok=True)
		except OSError:
			tmpDir = None
		fd, tmp = tempfile.mkstemp(suffix=".pem", dir=tmpDir)
		try:
			with os.fdopen(fd, "wb") as f:
				f.write(self._key or b"")
				if not (self._key or b"").endswith(b"\n"):
					f.write(b"\n")
				f.write(self._cert or b"")
			ctx.load_cert_chain(tmp)
		finally:
			try:
				os.unlink(tmp)
			except OSError:
				pass
		return ctx
