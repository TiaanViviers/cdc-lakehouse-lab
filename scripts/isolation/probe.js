// Run only inside a single-network disposable probe container.
const net = require('node:net');
const dns = require('node:dns').promises;
const udp = require('node:dgram');
const [mode, host, port, address] = process.argv.slice(2);
const name = 'sentinel.isolation.test';
const marker = 'cdc-isolation-v1';

async function main() {
  if (mode === 'serve') {
    net.createServer(socket => socket.end(marker)).listen(8181, host);
    if (address) {
      const server = udp.createSocket('udp4');
      server.on('message', (query, peer) => {
        const question = Buffer.from('\x08sentinel\x09isolation\x04test\x00\x00\x01\x00\x01', 'binary');
        if (!query.subarray(12, 12 + question.length).equals(question)) return;
        const header = Buffer.from([0,0,0x84,0,0,1,0,1,0,0,0,0]);
        query.copy(header, 0, 0, 2);
        const answer = Buffer.from([0xc0,12,0,1,0,1,0,0,0,0,0,4,...address.split('.').map(Number)]);
        server.send(Buffer.concat([header, question, answer]), peer.port, peer.address);
      });
      server.bind(53, address);
    }
    return;
  }
  if (mode === 'dns') {
    const resolver = new dns.Resolver({timeout: 500, tries: 1});
    resolver.setServers([host]);
    const answers = await resolver.resolve4(name);
    if (answers.join() !== address) throw Error('unexpected DNS answer ' + answers);
    console.log(answers.join());
    return;
  }
  const socket = net.connect(Number(port), host);
  let body = '';
  socket.setTimeout(1500, () => socket.destroy(Object.assign(Error(), {code:'ETIMEDOUT'})));
  socket.on('data', chunk => { body += chunk; });
  await new Promise((resolve, reject) => socket.on('error', reject).on('end', resolve));
  if (body !== marker) throw Error('wrong TCP marker');
  console.log(body);
}
main().catch(error => {
  console.error(error.code || error.message);
  process.exitCode = 1;
});
