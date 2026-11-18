// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'

const config = { current: { features: { tripadvisor: true } } }
vi.mock('../hooks/useClientConfig', () => ({
  useClientConfig: () => ({ config: config.current, loaded: true }),
  featureOn: (c, name) => c?.features?.[name] === true || c?.features?.[name] === 1,
}))
const fetchTripadvisorAttractions = vi.fn()
vi.mock('../services/api', () => ({
  fetchTripadvisorAttractions: (...a) => fetchTripadvisorAttractions(...a),
}))

import TripadvisorBlock from './TripadvisorBlock'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const OK = {
  status: 'ok',
  attribution: { name: 'Tripadvisor', logo_url: 'https://static.tacdn.com/logo.svg' },
  items: [
    {
      id: 1, name: 'Louvre Museum', rating: 4.5, num_reviews: 12345,
      rating_image_url: 'https://www.tripadvisor.com/img/4.5.svg',
      ranking: '#1 of 3,000 things to do in Paris', category: 'Museums',
      web_url: 'https://www.tripadvisor.com/Attraction_Review-d1',
    },
    {
      id: 2, name: 'Eiffel Tower', rating: 4.5, num_reviews: 1,
      rating_image_url: null, ranking: null, category: null,
      web_url: 'https://www.tripadvisor.com/Attraction_Review-d2',
    },
  ],
}

describe('TripadvisorBlock', () => {
  let container, root
  const render = (props) => act(() => root.render(
    <TripadvisorBlock token="tok" destinations={['Paris']} {...props} />,
  ))
  const click = async (el) => { await act(async () => { el.click() }) }
  const showButton = () => container.querySelector('[data-tid="results.tripadvisor.show"]')

  beforeEach(() => {
    config.current = { features: { tripadvisor: true } }
    fetchTripadvisorAttractions.mockReset()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('is hidden when the backend does not report features.tripadvisor', () => {
    config.current = { features: {} }
    render()
    expect(container.innerHTML).toBe('')
  })

  it('is hidden when signed out', () => {
    render({ token: null })
    expect(container.innerHTML).toBe('')
  })

  it('fetches nothing until the traveller asks', () => {
    render()
    expect(fetchTripadvisorAttractions).not.toHaveBeenCalled()
    expect(showButton().textContent).toBe('Show Tripadvisor ratings')
  })

  it('renders ratings with the Tripadvisor logo and links back on every name and review count', async () => {
    fetchTripadvisorAttractions.mockResolvedValue(OK)
    render()
    await click(showButton())
    expect(fetchTripadvisorAttractions).toHaveBeenCalledWith('Paris', 'tok')
    const block = container.querySelector('[data-testid="tripadvisor-block"]')
    expect(block.hasAttribute('data-nosnippet')).toBe(true)
    expect(block.textContent).toContain('Ratings from Tripadvisor')
    const logo = container.querySelector('img[alt="Tripadvisor"]')
    expect(logo.getAttribute('src')).toBe('https://static.tacdn.com/logo.svg')
    expect(logo.closest('a').getAttribute('href')).toBe('https://www.tripadvisor.com/')

    const names = [...container.querySelectorAll('[data-tid="results.tripadvisor.name"]')]
    expect(names.map(a => a.textContent)).toEqual(['Louvre Museum', 'Eiffel Tower']) // Tripadvisor's order
    expect(names[0].getAttribute('href')).toBe('https://www.tripadvisor.com/Attraction_Review-d1')
    expect(names[0].getAttribute('target')).toBe('_blank')
    expect(names[0].getAttribute('rel')).toContain('nofollow')

    const reviews = [...container.querySelectorAll('[data-tid="results.tripadvisor.reviews"]')]
    expect(reviews[0].textContent).toBe('12,345 reviews')
    expect(reviews[1].textContent).toBe('1 review')
    expect(reviews[0].getAttribute('href')).toBe('https://www.tripadvisor.com/Attraction_Review-d1')

    expect(container.querySelector('img[alt="Tripadvisor bubble rating: 4.5 of 5"]')).not.toBeNull()
    expect(block.textContent).toContain('#1 of 3,000 things to do in Paris')
    expect(block.textContent).toContain('not stored')
  })

  it('shows the paused state at the budget cap', async () => {
    fetchTripadvisorAttractions.mockResolvedValue({ status: 'paused', items: [] })
    render()
    await click(showButton())
    expect(container.querySelector('[data-testid="tripadvisor-paused"]').textContent)
      .toBe('Tripadvisor ratings are paused right now.')
    expect(container.querySelector('[data-tid="results.tripadvisor.name"]')).toBeNull()
  })

  it('shows an error with retry', async () => {
    fetchTripadvisorAttractions.mockRejectedValueOnce(new Error('502')).mockResolvedValueOnce(OK)
    render()
    await click(showButton())
    expect(container.textContent).toContain("Couldn't load Tripadvisor ratings")
    await click(container.querySelector('[data-tid="results.tripadvisor.retry"]'))
    expect(fetchTripadvisorAttractions).toHaveBeenCalledTimes(2)
    expect(container.querySelectorAll('[data-tid="results.tripadvisor.name"]')).toHaveLength(2)
  })

  it('offers one button per city on a multi-city trip', async () => {
    fetchTripadvisorAttractions.mockResolvedValue(OK)
    render({ destinations: ['Paris', 'Rome', 'Paris'] })
    const buttons = [...container.querySelectorAll('[data-tid="results.tripadvisor.show"]')]
    expect(buttons.map(b => b.textContent)).toEqual([
      'Show Tripadvisor ratings for Paris',
      'Show Tripadvisor ratings for Rome',
    ])
    await click(buttons[1])
    expect(fetchTripadvisorAttractions).toHaveBeenCalledWith('Rome', 'tok')
  })

  it('never writes Tripadvisor content to browser storage', async () => {
    fetchTripadvisorAttractions.mockResolvedValue(OK)
    localStorage.clear()
    sessionStorage.clear()
    render()
    await click(showButton())
    const stored = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage })
    expect(stored).not.toContain('Louvre')
  })
})
