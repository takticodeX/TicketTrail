import { describe, expect, it } from 'vitest';

import { DEFAULT_USERNAMES, detectHost } from './gitHosts';

describe('detectHost', () => {
  it.each([
    ['https://dev.azure.com/acme/proj/_git/repo', 'azure_repos'],
    ['https://acme.visualstudio.com/proj/_git/repo', 'azure_repos'],
    ['https://github.com/acme/app.git', 'github'],
    ['https://gitlab.com/group/sub/app.git', 'gitlab'],
    ['https://bitbucket.org/acme/app.git', 'bitbucket'],
    ['https://git.example.com/acme/app.git', 'generic'],
    ['https://github.com.evil.example/acme/app.git', 'generic'],
    ['not a url', 'generic'],
  ])('%s is %s', (url, host) => {
    expect(detectHost(url)).toBe(host);
  });
});

it('suggests the usernames from the spec', () => {
  expect(DEFAULT_USERNAMES).toEqual({
    azure_repos: 'pat',
    github: 'x-access-token',
    gitlab: 'oauth2',
    bitbucket: 'x-token-auth',
    generic: null,
  });
});
